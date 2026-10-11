"""Short, condition-led actions; road treatments require a site assessment."""
# Each entry is tanod, municipal engineering, and public education.
CAUSE = {
 'alcohol': ('Conduct ronda to observe suspected impaired driving; report dangerous behavior to the PNP and help arrange a sober ride.', 'Review the underlying incident reports before selecting any road treatment; alcohol involvement alone does not identify a road defect.', 'Remind drivers not to drink and drive; arrange a sober driver or ride home.'),
 'loss of control': ('Conduct ronda and observe abrupt braking, swerving or loss of vehicle control; log observations and refer dangerous driving to the PNP.', 'Inspect bends and road edges; repair damaged surfaces and restore faded edge markings.', 'Teach slowing before bends, smooth braking and checking tire condition.'),
 'speed': ('Conduct visible ronda, give speed-limit reminders and report dangerous driving to the PNP for authorized enforcement.', 'Check speeds and speed-limit signs; assess suitable traffic-calming measures with the road owner.', 'Explain posted speed limits and the extra distance needed to stop at higher speeds.'),
 'overtaking': ('During ronda, observe unsafe overtaking; log observed incidents and coordinate with the PNP.', 'Check visibility ahead; restore centerlines and approved no-overtaking signs where needed.', 'Teach staying behind when the view is blocked and overtaking only where permitted and clear.'),
 'slippery': ('During ronda, check for water pooling and slippery sections; warn traffic and report confirmed hazards to barangay officials.', 'Clear blocked drains and repair surfaces with poor grip; correct water pooling after inspection.', 'Remind drivers to slow on wet roads, leave more braking room and avoid sudden turns.'),
 'animal': ('During ronda, watch for roaming animals; alert owners and assist traffic safely while animals are removed.', 'Identify animal-entry points; assess warning signs or barriers where crossings recur.', 'Ask owners to secure animals; remind drivers to slow without swerving suddenly.'),
 'mechanical': ('During ronda, watch for stalled vehicles; warn approaching traffic and request roadside assistance.', 'Check safe stopping space and visibility for disabled vehicles after reviewing the incident reports.', 'Share a pre-trip checklist for brakes, tires and lights; repair faults before travel.'),
 'environment': ('During ronda, check for flooding, debris and blocked views; warn traffic and report confirmed hazards.', 'Inspect drainage, lighting and blocked views; repair confirmed hazards.', 'Share verified road hazards and advice to slow down or use a safer route.'),
 'reckless': ('Conduct ronda, record observed dangerous driving and refer incidents to the PNP.', 'Inspect junction visibility and lane guidance; correct confirmed deficiencies.', 'Remind drivers to put phones away, leave safe gaps and rest before driving.'),
}
COLLISION = {
 'self-accident': ('Conduct ronda and observe abrupt braking or swerving; log unsafe movements and report dangerous incidents to barangay officials.', 'Repair confirmed surface and road-edge defects; assess barriers where dangerous drops are found.', 'Teach smooth braking, slowing before bends and checking tires.'),
 'head-on': ('During ronda, observe unsafe lane crossing and overtaking; report dangerous incidents to the PNP.', 'Restore faded centerlines; assess bend visibility and opposing-traffic separation.', 'Remind drivers to stay in their lane and avoid overtaking with a blocked view.'),
 'rear-end': ('During ronda, monitor queues and abrupt stops; assist traffic where assigned and warn approaching drivers when vehicles stop.', 'Check queue visibility; improve advance warnings and stopping-area layout where needed.', 'Teach safe following gaps and early signals before slowing or stopping.'),
 'side-swipe': ('During ronda, observe close passing and lane obstructions; assist traffic where assigned and report blocked lanes.', 'Restore lane markings and review parking or loading areas that narrow the road.', 'Teach mirror and blind-spot checks, early signaling and safe passing space.'),
 'hit and run': ('Conduct visible ronda; promptly relay witnessed crash details to the PNP and request emergency assistance.', 'Review incident reports for visibility issues before selecting lighting or sign improvements.', 'Explain stopping safely, calling for help and reporting crash details without sharing victims\' identities.'),
}
VEHICLE = {
 'pedestrian': ('Assist crossings at assigned locations and report blocked walking routes.', 'Inspect walking routes; assess continuous sidewalks, visible crossings and safe crossing speeds.', 'Teach using safe crossings; remind drivers to yield and check for people before turning.'),
 'bicycle': ('Report close passing and obstructions along cycling routes.', 'Repair road-edge defects and assess safe cycling space at junctions.', 'Teach visible riding and remind motorists to leave safe passing space.'),
 'single motor': ('Give helmet reminders during rounds and report road-surface hazards.', 'Repair potholes and uneven surfaces; check drainage grates for motorcycle hazards.', 'Teach correct helmet use, smooth braking and tire checks.'),
 'tricycle': ('Assist orderly loading at assigned stops and report blocked junctions.', 'Review loading areas and joining traffic; improve markings and visibility where needed.', 'Remind operators to load safely, signal early and pick up passengers at safe stops.'),
 'truck': ('Assist traffic at assigned junctions and report unsafe truck movements.', 'Check turning space and visibility; assess separation from walking routes.', 'Explain truck blind spots, wide turns and safe following space.'),
 'bus': ('Assist passenger flow at assigned stops and keep junctions clear.', 'Assess bus-stop placement, passenger access and visibility when rejoining traffic.', 'Teach safe boarding and remind drivers to check for people before pulling away.'),
}
DEFAULT = ('Conduct ronda, observe traffic movements and record unsafe behavior; assist traffic where assigned and report incidents to barangay officials.',
           'Review the underlying incident reports with barangay officials before selecting roads for inspection.',
           'Share verified local hazards and safe-driving reminders.')


def concise_actions(values, periods):
    """Combine complementary evidence, without inventing locations or crash causes."""
    cause = values.get('cause', '').lower().replace('over speeding', 'overspeeding')
    collision = values.get('collision_type', '').lower()
    vehicle = values.get('vehicle_involved', '').lower()
    cause_steps = next((v for k,v in CAUSE.items() if k in cause), None)
    collision_steps = next((v for k,v in COLLISION.items() if k in collision), None)
    vehicle_steps = [v for k,v in VEHICLE.items() if k in vehicle]
    chosen = cause_steps or collision_steps or (vehicle_steps[0] if vehicle_steps else DEFAULT)
    actions = list(chosen)
    motorcycle = 'single motor' in vehicle
    single = 'self-accident' in collision
    # A collision category describes the event, not the cause or road condition.
    if single and motorcycle and not cause_steps:
        actions = [
            'Conduct ronda to observe motorcycle swerving, abrupt braking and unsafe riding; log observations and refer dangerous incidents to the PNP.',
            'Confirm roads from incident records; inspect uneven surfaces, drainage grates and road-edge drops before selecting repairs.',
            'Teach motorcycle riders smooth braking, slowing before turns, correct helmet fit and tire checks.',
        ]
    elif cause_steps and collision_steps and collision_steps != cause_steps:
        # Engineering can address the collision mechanism as well as the reported cause.
        if not ('loss of control' in cause and single):
            actions[1] += ' ' + collision_steps[1]
    if motorcycle and not (single and not cause_steps):
        actions[0] += ' Include helmet reminders for motorcycle riders.'
        actions[1] += ' Check uneven surfaces and drainage grates for motorcycle hazards.'
        actions[2] += ' Include helmet fit and tire checks for motorcycle riders.'
    for key in ('pedestrian', 'bicycle', 'tricycle', 'truck', 'bus'):
        if key in vehicle and chosen != VEHICLE[key]:
            extra = VEHICLE[key]
            actions[0] += ' ' + extra[0]
            actions[1] += ' ' + extra[1]
            actions[2] += ' ' + extra[2]
    severity = values.get('severity', '').lower()
    if severity == 'fatal':
        actions[0] += ' Keep emergency access clear and promptly request responders when a crash occurs.'
        actions[1] = 'Prioritize a joint fatal-crash review. ' + actions[1]
        actions[2] += ' Explain how to call for help without entering moving traffic.'
    elif severity == 'non-fatal':
        actions[0] += ' Request medical assistance for injuries; give first aid only within training.'
        actions[2] += ' Explain safe help-seeking after an injury.'
    period = periods.get(values.get('time_period'), values.get('time_period'))
    night = values.get('time_period') in ('8:01PM-12MN', '12:01AM-4AM')
    if night:
        actions[0] += ' Use reflective equipment at night; report visibility problems.'
        actions[1] += ' Check lighting and reflective markings after dark.'
        actions[2] += ' Include working lights and visibility during night travel.'
    elif values.get('time_period') in ('4:01AM-8AM', '4:01PM-8PM'):
        actions[1] += ' Check visibility at dawn or dusk.'
        actions[2] += ' Explain adjusting speed when glare or changing light reduces visibility.'
    context = []
    if values.get('barangay'): context.append('in ' + values['barangay'])
    if values.get('day'): context.append('on ' + values['day'])
    if period: context.append('during ' + period)
    if context:
        scope = ', '.join(context)
        actions[0] += ' Schedule these duties ' + scope + '.'
        actions[1] += ' Schedule observations ' + scope + '.'
        audience = ' in ' + values['barangay'] if values.get('barangay') else ''
        when = (' before ' + period) if period else ''
        if values.get('day'): when += ' on ' + values['day']
        actions[2] += ' Share these reminders' + audience + when + '.'
    if not values.get('barangay'):
        if 'incident records' not in actions[1] and 'incident reports' not in actions[1]:
            actions[1] = 'Confirm locations from incident records. ' + actions[1]
    actions[2] = 'Run a campaign on official LGU and barangay Facebook pages using short videos or illustrated posts. ' + actions[2]
    return actions
