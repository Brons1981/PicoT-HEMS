"""Real dashboard HTTP boundary, canonical settings and replan notification."""

import json
from functools import partial
from threading import Event
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_route_choice_web import server_for

from picot.v2.live_runtime import PlanningResetBarrier, _update_user_rules_and_replan
from picot.v2.user_rules import UserRuleStore
from picot.v2.web_ui import WebViewStore


def test_position_only_http_request_changes_real_store_and_requests_replan(tmp_path):
    rules = UserRuleStore(tmp_path / 'rules.json', migrated_trading_soc_percent=25)
    rules.update(market_minimum_spread_eur_per_kwh=.05)
    event, activated, view = Event(), [], WebViewStore()
    view.set_user_rule_update(partial(
        _update_user_rules_and_replan, store=rules, barrier=PlanningResetBarrier(),
        replan_requested=event, web_view_store=view, activate_profile=activated.append,
    ))
    # The real callback takes a keyword payload; adapt only the HTTP callable seam.
    update = view.user_rule_update()
    view.set_user_rule_update(lambda payload: update(payload=payload))
    with server_for(view) as base:
        for position, expected in [(0, 0), (1, 12.5), (2, 25), (3, 37.5)]:
            event.clear()
            request = Request(base + '/api/user-rules',
                              data=json.dumps({'strategy_position': position}).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=5) as response:
                data = json.loads(response.read())
            assert data['replan_requested'] is True and event.is_set()
            assert data['user_rules']['maximum_trading_soc_percent'] == expected
            assert activated[-1] == rules.current()
            assert data['user_rule_revision'] == rules.current().revision
        before = rules.current()
        request = Request(base + '/api/user-rules', data=b'{"strategy_position":4}',
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            urlopen(request, timeout=5)
        except HTTPError as error:
            assert error.code == 400
        else:
            raise AssertionError('Unimplemented trading mode must not be accepted')
        assert rules.current() == before
