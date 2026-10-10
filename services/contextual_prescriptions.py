"""Deterministic, reviewable action templates; associations do not establish causes.
Local expert review is required for every proposed plan before deployment.
"""
import hashlib

DOMAINS = ('enforcement', 'engineering', 'education')
SOURCE = 'https://www.who.int/publications/i/item/save-lives-a-road-safety-technical-package'
# Each tuple: enforcement, engineering, public information & education.
CAUSES = {
 'loss of control': ('Observe speeds and unsafe manoeuvres on the routes in these records; use the observations to schedule patrols.', 'Inspect bends, surface grip, potholes, drainage and edge markings; prioritise confirmed defects for repair.', 'Demonstrate slowing before bends, leaving room to brake and checking tyres before travel.'),
 'over speeding': ('Use trained traffic officers to carry out speed checks at approved, safe locations.', 'Measure operating speeds and assess signs, road markings and suitable traffic-calming treatments.', 'Explain the posted speed limits and how speed increases stopping distance.'),
 'human error': ('Observe unsafe speed, following distance and turning behaviour before choosing a focused patrol activity.', 'Audit sight lines, lane guidance and junction visibility where the records cluster.', 'Teach safe following distance, careful turning and speed choices; avoid blaming all drivers for an unspecified error.'),
 'alcohol intake': ('Ask authorised officers to plan drink-driving checks using approved procedures and safe stopping areas.', 'Inspect lighting and safe stopping locations near the recorded sites; assess safer pickup areas with operators.', 'Promote a sober driver or safe ride home and ask local establishments to share the message.'),
 'wrong overtaking': ('Observe and address unsafe overtaking and lane use at approved patrol locations.', 'Check sight distance, centre lines and no-overtaking signs at the recorded sites.', 'Explain when overtaking is unsafe and demonstrate waiting for a clear, permitted opportunity.'),
 'slippery road': ('Arrange traffic control and speed reminders when the surface is wet or slippery.', 'Inspect drainage, surface friction and contamination; clear drains and propose treatment of confirmed defects.', 'Share wet-road advice: slow down, leave extra braking room and avoid sudden turns.'),
 'animal on road': ('Coordinate with barangay personnel to report and safely manage roaming animals near the recorded sites.', 'Inspect animal-entry points and assess appropriate warning signs and barriers with the road owner.', 'Ask animal owners to secure their animals and show drivers how to slow safely when animals are present.'),
 'mechanical failure': ('Coordinate roadworthiness checks with authorised personnel, focusing on tyres, brakes and lights.', 'Assess safe pull-off areas and visibility around locations where disabled vehicles obstruct traffic.', 'Share a short tyre, brake and light inspection checklist with drivers and fleet operators.'),
 'environmental factor': ('Visit the sites to establish whether visibility, obstructions or weather require temporary traffic control.', 'Inspect lighting, sight lines, drainage and roadside obstructions; repair only confirmed problems.', 'Share verified local visibility or weather hazards and practical route or speed advice.'),
 'reckless': ('Focus observation on distraction, unsafe manoeuvres and fatigue-related behaviour at the recorded sites.', 'Review lane guidance, conflict points and forgiving roadsides with the road owner.', 'Promote phone-free driving, rest breaks and stopping safely when unwell or tired.'),
 'collision': ('Review the incident narratives and observe conflicting traffic movements before selecting an enforcement focus.', 'Audit junction movements, sight lines and road markings at the recorded collision sites.', 'Explain safe gaps, right-of-way and checking for other road users before turning.'),
}
COLLISIONS = {
 'head-on': ('Watch unsafe overtaking and crossing of the centre line.', 'Inspect centre-line visibility, opposing-flow separation and bend sight distance.', 'Show why drivers should stay in their lane and avoid overtaking without a clear view.'),
 'side-swipe': ('Observe unsafe lane changes and obstruction of travel lanes.', 'Inspect lane width, edge markings and roadside parking conflicts.', 'Teach mirror checks, blind-spot checks and adequate passing space.'),
 'rear-end': ('Observe tailgating and abrupt stopping at the recorded sites.', 'Check queue visibility, advance warnings and junction approach markings.', 'Demonstrate safe following distance and early signalling before slowing.'),
 'self-accident': ('Observe unsafe speed and abrupt manoeuvres without assuming a cause from the collision type.', 'Inspect road edges, bends, surface defects and roadside hazards.', 'Teach controlled braking, safe cornering and checking tyres before travel.'),
 'hit and run': ('Review incident locations and available reports; plan visible patrols and a safe reporting process.', 'Check visibility and lighting at the recorded sites and report repair needs.', 'Explain safe incident reporting and seeking help; do not post victims or identifying details.'),
}
VEHICLES = {
 'single motor': ('Check helmet use and unsafe riding through authorised officers.', 'Inspect surface defects and drainage grates that can destabilise two-wheelers.', 'Target rider groups with helmet-fit, visibility and safe-cornering demonstrations.'),
 'bicycle': ('Observe close passing and conflicts involving cyclists.', 'Assess safe road-edge space, junction visibility and cycling conflict points.', 'Share visible-riding and safe-passing advice with cyclists and motorists.'),
 'tricycle': ('Observe unsafe loading, stopping and merging by tricycles.', 'Review pickup areas and merging conflicts with tricycle operators.', 'Work with tricycle associations on safe loading, signalling and passenger pickup.'),
 'truck': ('Coordinate checks on unsafe truck speed, loads and turning with authorised officers.', 'Check turning space, sight lines and heavy-vehicle conflicts at junctions.', 'Use fleet briefings and social posts to explain truck blind spots and safe following space.'),
 'bus': ('Observe bus stopping, loading and unsafe overtaking.', 'Assess bus stops, passenger access and re-entry into traffic.', 'Brief bus operators and passengers on safe boarding and overtaking risks.'),
 'pedestrian': ('Manage yielding and parking that blocks pedestrian visibility.', 'Assess crossings, walking space, lighting and pedestrian sight lines.', 'Share safe-crossing and driver-yielding messages with local groups.'),
 'animal': CAUSES['animal on road'],
}
PERIODS = {
 '12:01AM-4AM': '12:01 AM–4 AM', '4:01AM-8AM': '4:01 AM–8 AM',
 '8:01AM-12NN': '8:01 AM–12 noon', '12:01PM-4PM': '12:01 PM–4 PM',
 '4:01PM-8PM': '4:01 PM–8 PM', '8:01PM-12MN': '8:01 PM–12 midnight',
}


def feature_steps(field, value):
    v = value.lower()
    if v.startswith('unknown') or v in ('', 'nan'):
        return tuple(f'Ask records staff to verify the missing {field.replace("_", " ")} before choosing a targeted measure.' for _ in DOMAINS)
    if field == 'cause':
        return next((s for k,s in CAUSES.items() if k in v), (
            f'Review reports for the recorded cause “{value}” and observe related behaviour before planning a patrol.',
            f'Have an engineer inspect the sites for road conditions related to “{value}” before choosing repairs.',
            f'Ask the road-safety team to verify practical prevention advice for “{value}” before publishing the campaign.'))
    if field == 'collision_type':
        return next((s for k,s in COLLISIONS.items() if k in v), CAUSES['collision'])
    if field == 'vehicle_involved':
        matches = [s for k,s in VEHICLES.items() if k in v]
        if matches: return tuple(' '.join(dict.fromkeys(s[i] for s in matches)) for i in range(3))
        return (f'Observe speed, restraint use and unsafe movements involving {value}.',
                f'Check junction access, stopping space and visibility for {value} at the recorded sites.',
                f'Provide drivers and operators of {value} with safe-speed, restraint and following-distance reminders.')
    if field == 'barangay':
        return (f'Coordinate with {value} barangay officials to identify the exact roads in the reports and roster patrol staff there.',
                f'Arrange a joint site walk in {value}; list confirmed defects, the responsible road owner and repair priorities.',
                f'Ask {value} barangay pages and community groups to share the campaign and collect local hazard reports.')
    if field == 'day':
        return (f'Roster observations and patrols on {value}; compare findings with other days before extending the schedule.',
                f'Observe traffic on {value} and schedule disruptive repairs outside the recorded busy period.',
                f'Publish reminders the day before {value} and repeat them before the rule’s time window, if one is recorded.')
    if field == 'time_period':
        t = PERIODS.get(value, value)
        night = any(k in value.upper().replace(' ', '') for k in ('MN', '12:01AM', '8:01PM', '8PM'))
        transition = value in ('4:01AM-8AM', '4:01PM-8PM')
        lighting = 'Check lighting, reflective markings and sight distance after dark; carry out repairs in daylight.' if night else ('Inspect glare, lighting and crossing visibility during the dawn or dusk portion of this window.' if transition else 'Observe junction movements, queues and crossing visibility during this window; repair outside busy hours.')
        return (f'Deploy the approved patrol plan during {t}; brief staff before the window and use a safe, visible stopping position.' + (' Check vehicle lights and watch for fatigue; do not infer alcohol use unless the rule records it.' if night else ''),
                f'Visit the recorded sites during {t}. {lighting}',
                f'Schedule the rule-specific social-media reminder before {t}, with a repeat near the start of the window.' + (' Include safe rides home, working lights and rest before driving.' if night else ' Include the travel conditions observed during that window.'))
    if field == 'severity':
        if v == 'fatal':
            return ('Prioritise a joint review of fatal records and coordinate patrol access with emergency responders.',
                    'Conduct a fatal-crash site review; assess speed, roadside hazards and protection for vulnerable road users.',
                    'Use an anonymised serious-crash prevention message and explain how to call for help safely.')
        if v == 'damage-to-property':
            return ('Review minor-collision locations and maintain safe traffic flow while incidents are cleared.',
                    'Inspect low-speed conflict points, parking layouts and visibility.',
                    'Share safe manoeuvring and incident-reporting guidance without suggesting that these crashes are harmless.')
        return ('Review injury records and focus on protective equipment and unsafe manoeuvres observed at the sites.',
                'Inspect pedestrian protection, road edges and impact hazards to reduce injury severity.',
                'Include correctly worn helmets, seat belts and safe help-seeking in the campaign.')
    raise ValueError(f'Unsupported mining feature: {field}')


def contextual_actions(rule, labels):
    items = [tuple(i) for i in rule.get('items', [])]
    if not items: return []
    context = '; '.join(f'{labels[f]}: {PERIODS.get(v,v)}' for f,v in items)
    digest = hashlib.sha256(repr(sorted(items)).encode()).hexdigest()[:12]
    values = dict(items)
    # One primary intervention, qualified by the complete rule context.
    priority = ('cause', 'collision_type', 'vehicle_involved', 'severity', 'barangay', 'day', 'time_period')
    primary = next(f for f in priority if f in values)
    target = []
    if 'vehicle_involved' in values: target.append('involving ' + values['vehicle_involved'])
    if 'collision_type' in values: target.append('recorded as ' + values['collision_type'])
    if 'severity' in values: target.append('with ' + values['severity'].lower() + ' outcomes')
    if 'barangay' in values: target.append('in ' + values['barangay'])
    if 'day' in values: target.append('on ' + values['day'])
    scope = (' Focus on records ' + ', '.join(target) + '.') if target else ''
    period = PERIODS.get(values.get('time_period'), values.get('time_period'))
    night = values.get('time_period') in ('8:01PM-12MN', '12:01AM-4AM')
    actions = []
    for i, domain in enumerate(DOMAINS):
        core = feature_steps(primary, values[primary])[i]
        if domain == 'education':
            core = 'Use official LGU or barangay Facebook posts and a community briefing to ' + core[0].lower() + core[1:]
        if domain == 'education' and primary == 'barangay':
            core = 'Run a barangay road-safety campaign on official LGU and barangay Facebook pages, using verified local hazard reports.'
        timing = ''
        if period and primary != 'time_period':
            if domain == 'enforcement': timing = f' Schedule this activity during {period}, using a safe observation or stopping location.'
            elif domain == 'engineering': timing = f' Inspect during {period}' + (' to check lighting and visibility; schedule repairs in daylight.' if night else '; schedule repairs outside busy hours.')
            else: timing = f' Publish the reminder before {period} and repeat it near the start of that window.'
        elif domain == 'education' and primary == 'time_period':
            core = f'Publish official LGU or barangay Facebook reminders before {period} about ' + ('working lights, safe speeds and resting before driving.' if night else 'safe speeds, following distance and checking for other road users.')
        action = core + scope + timing
        actions.append(dict(id=f'PLAN-{digest}-{domain}', agency=domain, status='Candidate',
            status_label='Proposed', validation_status='Pending expert validation',
            action=action, steps=[action], context=context, applies_when=context,
            matched_on=[dict(field=labels[f],value=PERIODS.get(v,v)) for f,v in items],
            evidence_source=SOURCE, contextual=True))
    return actions
