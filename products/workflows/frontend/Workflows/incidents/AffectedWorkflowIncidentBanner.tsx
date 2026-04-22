import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

// Incident reference link. Backed by the server-side list populated from the
// WORKFLOWS_INCIDENT_2026_04_22_AFFECTED_IDS env var; the banner only renders when the serializer
// sets affectedByIncident2026_04_22 = true for the current workflow.
const INCIDENT_2026_04_22_URL = 'https://posthog.com/incidents/2026-04-22-workflow-dedup-false-positives'

export function AffectedWorkflowIncidentBanner({ affected }: { affected?: boolean }): JSX.Element | null {
    if (!affected) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-2">
            <strong>Heads up:</strong> this workflow was affected by an incident between April 1 and April 22, 2026,
            where some <code>Wait Until</code> steps were incorrectly skipped as duplicates. The underlying bug has been
            fixed and runs after April 22 are executing normally. Past runs during the affected window may not have
            completed.{' '}
            <Link to={INCIDENT_2026_04_22_URL} target="_blank">
                Read more
            </Link>
            .
        </LemonBanner>
    )
}
