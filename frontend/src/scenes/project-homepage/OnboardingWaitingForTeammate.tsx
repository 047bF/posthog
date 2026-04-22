import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { IconHourglass } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

const FOCUS_REFRESH_THROTTLE_MS = 30_000

export function OnboardingWaitingForTeammate(): JSX.Element {
    const { user } = useValues(userLogic)
    const { loadUser, loadUserSuccess } = useActions(userLogic)
    const orgName = user?.organization?.name ?? 'your team'
    const pendingInviteId = user?.onboarding_delegated_to_invite ?? null
    const [isTakingOver, setIsTakingOver] = useState(false)
    const lastRefreshRef = useRef<number>(0)

    // Refresh when the tab regains focus so the screen transitions automatically once the
    // teammate accepts — but throttle so rapid tab-switching doesn't hammer /api/users/@me/.
    useEffect(() => {
        const onFocus = (): void => {
            // Stop polling once the delegation is resolved — no more state changes to pick up.
            if (user?.onboarding_delegation_accepted_at) {
                return
            }
            const now = Date.now()
            if (now - lastRefreshRef.current < FOCUS_REFRESH_THROTTLE_MS) {
                return
            }
            lastRefreshRef.current = now
            loadUser()
        }
        window.addEventListener('focus', onFocus)
        return () => window.removeEventListener('focus', onFocus)
    }, [loadUser, user?.onboarding_delegation_accepted_at])

    const takeOverSetup = async (): Promise<void> => {
        if (isTakingOver) {
            return
        }
        setIsTakingOver(true)
        let deletionCommitted = false
        try {
            // Cancel the delegation invite first — on the backend this fires pre_delete
            // which clears the delegator's onboarding_skipped_at/reason via the signal. If we
            // just navigate to /onboarding, the sceneLogic suppression re-engages on the next
            // render and we bounce back here.
            if (pendingInviteId && user?.organization?.id) {
                await api.delete(`api/organizations/${user.organization.id}/invites/${pendingInviteId}/`)
                deletionCommitted = true
            }
            // Re-fetch user so kea state reflects the cleared delegation fields before the
            // sceneLogic redirect runs at the new route.
            const refreshed = await api.get('api/users/@me/')
            loadUserSuccess(refreshed)
            router.actions.push(urls.onboarding())
        } catch {
            if (deletionCommitted) {
                loadUser()
                router.actions.push(urls.onboarding())
                return
            }
            lemonToast.error("Couldn't cancel the delegation. Try again or manage invites in organization settings.")
            setIsTakingOver(false)
        }
    }

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
                    Manage invites
                </LemonButton>
                <LemonButton type="primary" onClick={takeOverSetup} loading={isTakingOver}>
                    Set up PostHog myself
                </LemonButton>
            </div>
        </SceneContent>
    )
}
