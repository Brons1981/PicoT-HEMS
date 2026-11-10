"""Late source feedback releases faults without dispatching or dropping manual holds."""
from unittest.mock import patch
from test_control import ControlFixture
from picot_hc.__main__ import Runtime


class FaultRecoveryTests(ControlFixture):
    def start(self):
        with patch('time.time', return_value=1800000000):
            c=self.ctl.submit(self.payload('cv','heating',21),120,origin='schedule')
        self.ctl.expire(c['deadline']+1)
        self.runtime.heating.data['faults']['cv']='No feedback'
        self.runtime.heating.data['owned']['cv']=dict(command=c['id'],since=c['created'])
        return c

    def feedback(self,c,value=21,mode='heat'):
        self.states[self.config['cv']]['state']=mode
        self.states[self.config['cv']]['attributes']['temperature']=value
        now=c['deadline']+30
        self.ctl.observe(self.states,now,now)
        self.runtime.heating.reconcile(now)
        return now

    def test_late_matching_feedback_clears_fault_without_retry(self):
        c=self.start();self.feedback(c)
        self.assertNotIn('cv',self.runtime.heating.data['faults'])
        record=next(r for r in self.ctl.records() if r['id']==c['id'])
        self.assertEqual(record['status'],'confirmed')
        self.assertEqual(record['recovered_from'],'timed_out')
        self.assertEqual(self.runtime.schedule.view(c['deadline']+30)['overrides'],[])
        self.assertEqual(len(self.calls),1)

    def test_mismatch_or_unavailable_does_not_clear(self):
        c=self.start()
        for mode,value in [('heat',20),('off',21),('unavailable',21)]:
            self.feedback(c,value,mode)
            self.assertIn('cv',self.runtime.heating.data['faults'])
        self.assertEqual(len(self.calls),1)

    def test_failed_request_only_recovers_when_actual_state_matches(self):
        self.status=400
        c=self.start()
        self.feedback(c,value=20)
        self.assertIn('cv',self.runtime.heating.data['faults'])
        self.feedback(c,value=21)
        self.assertNotIn('cv',self.runtime.heating.data['faults'])
        self.assertEqual(self.ctl.records()[0]['recovered_from'],'failed')
        self.assertEqual(len(self.calls),1)

    def test_newer_command_prevents_old_recovery(self):
        c=self.start()
        with patch('time.time',return_value=c['deadline']+2):
            self.ctl.submit(self.payload('cv','heating',22),120,origin='schedule')
        self.feedback(c)
        self.assertIn('cv',self.runtime.heating.data['faults'])
        self.assertEqual(next(r for r in self.ctl.records() if r['id']==c['id'])['status'],'timed_out')

    def test_manual_hold_survives_recovery(self):
        c=self.start()
        self.runtime.schedule.hold('cv','mode','off',c['deadline']+1,'Manual')
        self.feedback(c)
        self.assertNotIn('cv',self.runtime.heating.data['faults'])
        self.assertTrue(self.runtime.schedule.view(c['deadline']+30)['overrides'][0]['active'])
        self.assertNotIn('cv',self.runtime.heating.data['owned'])

    def test_confirmed_cleanup_clears_historical_fault_without_owner(self):
        c=self.start()
        self.apply=True
        with patch('time.time',return_value=c['deadline']+2):
            self.ctl.submit(self.payload('cv','mode','off'),120,origin='schedule')
        self.runtime.heating.data['owned'].clear()
        self.feedback(c,value=21,mode='off')
        self.assertNotIn('cv',self.runtime.heating.data['faults'])
        self.assertEqual(len(self.calls),1) # Already off; no second dispatch.

    def test_stale_feedback_does_not_clear_historical_fault(self):
        c=self.start()
        self.ctl.expire(c['deadline']+1)
        self.runtime.heating.reconcile(c['deadline']+300)
        self.assertIn('cv',self.runtime.heating.data['faults'])

    def test_interrupted_command_recovers_after_restart(self):
        with patch('time.time',return_value=1800000000):
            c=self.ctl.submit(self.payload('cv','heating',21),120,origin='schedule')
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        self.runtime,self.ctl=other,other.control
        other.heating.data['faults']['cv']='Interrupted'
        other.heating.data['owned']['cv']=dict(command=c['id'],since=c['created'])
        self.feedback(c)
        self.assertNotIn('cv',other.heating.data['faults'])
        self.assertEqual(self.ctl.records()[0]['recovered_from'],'interrupted')
        self.assertEqual(len(self.calls),1)
        other.heating.save()
        again=Runtime(self.config,self.store,self.url,'fake-secret')
        self.assertNotIn('cv',again.heating.data['faults'])
        self.assertIn('cv',again.heating.data['fault_recoveries'])
