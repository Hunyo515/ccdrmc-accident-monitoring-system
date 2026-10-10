# Review the prescriptions before field implementation

Every new tailored plan starts as **Pending expert validation**. Imported actions retain the source catalog's implementation status and require revalidation of their fit to the current pattern. This release contains no newly granted expert approval.

For each pattern, ask a representative from traffic enforcement, LGU engineering and public information/education to review their domain. Include the road owner and relevant barangay or operator where needed.

Record the pattern's feature values and support/confidence/lift; plan ID; dataset version/date; reviewer name, role and review date; decision (approve, revise, reject); rationale; proposed site and time; responsible office; equipment/staff and cost; success measure; and next review date. Do not treat a recorded cause as a proven finding without checking the incident reports.

| Domain | Questions for the reviewer | Practical follow-up measure |
|---|---|---|
| Enforcement | Are the staff authorised and equipped? Is the stopping/observation point safe? Is the schedule aligned to the rule? Does the plan avoid inferring violations that are not recorded? | Patrol coverage, observed speeds/behaviour, equipment use, and documented follow-up; citations alone are not a safety outcome. |
| Engineering | Has the actual site been visited under the recorded conditions? Is the proposed treatment suited to the road, traffic and owner? Are budgets, design and maintenance responsibilities clear? | Completed inspections, verified defects repaired, before/after speed or conflict observations, and a reviewed longer-term incident comparison. |
| Public Information & Education | Does the message match the audience, cause/collision context and travel time? Are local languages and non-social-media channels needed? Are claims accurate and privacy protected? | Audience reach, message recall, participation and observed behaviour; clicks/likes alone do not demonstrate crash reduction. |

For an 8:01 PM–12 midnight pattern, for example, review patrol staffing during that window, an after-dark visibility inspection followed by daylight repair work, and an approved social-media reminder before the window. Do not infer drink-driving from time alone.

When a rule also includes a cause, vehicle, barangay, weekday or severity, review those constraints together. A rule with no barangay does not identify a specific road; find the exact locations in its underlying records before scheduling work.

The new deterministic templates are in `services/contextual_prescriptions.py`. The imported actions and their original statuses are in `data/prescriptions.json`. Update template wording and catalogue validation metadata only after documenting the review, then restart and rerun tests. Runtime plan generation remains marked pending in this release; an audited approval-management interface is not part of this update.
