import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconHourglass } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

export function OnboardingWaitingForTeammate(): JSX.Element {
    const { user } = useValues(userLogic)
    const { loadUser } = useActions(userLogic)
    const orgName = user?.organization?.name ?? 'your team'

    // Refresh the user's delegation state when the tab regains focus so the screen
    // transitions automatically once the teammate accepts (or the invite is cancelled).
    useEffect(() => {
        const onFocus = (): void => loadUser()
        window.addEventListener('focus', onFocus)
        return () => window.removeEventListener('focus', onFocus)
    }, [loadUser])

    return (
        <SceneContent className="p-4 flex flex-col items-center justify-center text-center gap-3 max-w-screen-sm mx-auto">
            <IconHourglass className="text-4xl" />
            <h2 className="m-0">Waiting on your teammate</h2>
            <p className="text-secondary">
                We've sent an invite to finish setting up PostHog for <strong>{orgName}</strong>. Your data will appear
                here once they complete setup.
            </p>
            <div className="flex gap-2">
                <LemonButton type="secondary" to={urls.settings('organization-members')}>
                    View pending invites
                </LemonButton>
                <LemonButton type="primary" to={urls.onboarding()}>
                    Set it up myself instead
                </LemonButton>
            </div>
        </SceneContent>
    )
}
