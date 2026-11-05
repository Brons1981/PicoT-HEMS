"""Explain model coverage for a future three-way comparison; no control permission."""

from .energy_model import finite


def model_status(records, estimate, value_key, now, *, context_available, time_key='measured_at'):
    recent = sum(0 <= now-r[time_key] <= 7*86400 for r in records)
    matched = estimate.get('samples', estimate.get('cooling_samples', 0))
    ready = context_available and finite(estimate.get(value_key))
    reason = ('Schatting beschikbaar voor deze meetomstandigheden.' if ready else
              'Geen actuele bruikbare meetcontext; opgeslagen metingen blijven bewaard.'
              if not context_available else
              'Minder dan drie passende metingen in de laatste zeven dagen.' if matched < 3 else
              'Metingen aanwezig, maar de modelvoorwaarden leveren nog geen bruikbare schatting.')
    return dict(status='ready' if ready else 'waiting', stored=len(records), recent=recent,
                matching=matched, required=3, reason=reason, estimate=estimate)


def assess(runtime, plan, sample, now):
    steady = runtime.energy_proposals.model
    warmup = runtime.warmup_energy
    startup = runtime.startup_energy.model
    cooling = runtime.heating.learning.cooling
    thermal = plan.get('learning_context')
    reduced = dict(sample, target=18.0, indoor=18.0) if sample else None
    models = {}
    for name, model, query, key in (
        ('handhaven', steady, sample, 'power_w'),
        ('handhaven_18', steady, reduced, 'power_w'),
        ('opwarmen', warmup, runtime.warmup_sample, 'energy_wh'),
        ('start_uit', startup, runtime.startup_sample, 'energy_wh'),
    ):
        models[name] = model_status(model.records, model.estimate(query, now), key, now,
                                    context_available=query is not None)
    models['afkoelen'] = model_status(cooling.samples, cooling.estimate(thermal, now),
        'cooling_rate', now, context_available=bool(thermal and thermal.get('valid')),
        time_key='end')
    return dict(
        generated_at=now, execution_authorized=False, status='development', models=models,
        reason=('De gezamenlijke kostenvergelijking is nog in ontwikkeling; '
                'geen automatische strategie-keuze.'),
        scenarios=[
            dict(id='maintain', label='Temperatuur handhaven', requires=['handhaven']),
            dict(id='reduce', label='Verlagen naar minimaal 18 \u00b0C',
                 requires=['afkoelen', 'handhaven_18', 'opwarmen', 'handhaven']),
            dict(id='off', label='Uitschakelen en later opwarmen',
                 requires=['afkoelen', 'start_uit', 'handhaven']),
        ],
        missing_comparison=['Gelijke periode en comforteisen voor alle drie scenario\u0027s',
                            'Volledig prijsprofiel en kosten inclusief opnieuw opwarmen',
                            'Controle van kamerondergrens en apparaatgrenzen per traject'],
    )
