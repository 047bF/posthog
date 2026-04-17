import { useValues } from 'kea'

import { IconHourglass } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

export function OnboardingWaitingForTeammate(): JSX.Element {
    const { user } = useValues(userLogic)
    const orgName = user?.organization?.name ?? 'your team'

    return (
        <SceneContent className="p-4 flex flex-col items-center justify-center text-center gap-3 max-w-screen-sm mx-auto">
            <IconHourglass className="text-4xl" />
            <h2 className="m-0">Waiting on your teammate</h2>
            <p className="text-secondary">
                We've sent an invite to finish setting up PostHog for <strong>{orgName}</strong>. You'll see your data
                here once they complete setup.
            </p>
            <div className="flex gap-2">
                <LemonButton type="secondary" to={urls.settings('organization-members')}>
                    Manage pending invites
                </LemonButton>
                <LemonButton type="primary" to={urls.onboarding()}>
                    Set it up myself instead
                </LemonButton>
            </div>
        </SceneContent>
    )
}
