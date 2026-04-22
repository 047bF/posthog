import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { OrganizationInviteType, UserType } from '~/types'

import type { onboardingExitLogicType } from './onboardingExitLogicType'
import { onboardingLogic } from './onboardingLogic'

export type ExitReason = 'delegated' | 'later' | 'other'
export type ExitTab = 'delegate' | 'later'

const isValidEmail = (email: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())

/** Pull the most actionable detail out of an API error (DRF field errors, validation messages, or generic detail). */
function extractErrorDetail(error: any, fallback: string): string {
    if (!error) {
        return fallback
    }
    const data = error.data ?? error
    if (typeof data === 'string') {
        return data
    }
    if (data?.detail && typeof data.detail === 'string') {
        return data.detail
    }
    // DRF validation errors shape: { field: ["msg1", ...], ... }
    if (data && typeof data === 'object') {
        for (const key of Object.keys(data)) {
            const val = (data as any)[key]
            if (Array.isArray(val) && val.length && typeof val[0] === 'string') {
                return val[0]
            }
            if (typeof val === 'string') {
                return val
            }
        }
    }
    return error.message || fallback
}

export const onboardingExitLogic = kea<onboardingExitLogicType>([
    path(['scenes', 'onboarding', 'onboardingExitLogic']),
    connect(() => ({
        values: [onboardingLogic, ['stepKey'], userLogic, ['user']],
        actions: [userLogic, ['loadUser', 'loadUserSuccess']],
    })),
    actions({
        openExitModal: true,
        closeExitModal: true,
        setTargetEmail: (targetEmail: string) => ({ targetEmail }),
        setMessage: (message: string) => ({ message }),
        setTab: (tab: ExitTab) => ({ tab }),
        submitDelegation: true,
        submitSkip: true,
        setIsSubmitting: (isSubmitting: boolean) => ({ isSubmitting }),
    }),
    reducers({
        isExitModalOpen: [
            false,
            {
                openExitModal: () => true,
                closeExitModal: () => false,
            },
        ],
        targetEmail: [
            '',
            {
                setTargetEmail: (_, { targetEmail }) => targetEmail,
                closeExitModal: () => '',
            },
        ],
        message: [
            '',
            {
                setMessage: (_, { message }) => message,
                closeExitModal: () => '',
            },
        ],
        tab: [
            'delegate' as ExitTab,
            {
                setTab: (_, { tab }) => tab,
                closeExitModal: () => 'delegate' as ExitTab,
            },
        ],
        isSubmitting: [
            false,
            {
                setIsSubmitting: (_, { isSubmitting }) => isSubmitting,
                closeExitModal: () => false,
            },
        ],
    }),
    selectors({
        canSubmitDelegation: [(s) => [s.targetEmail], (targetEmail) => isValidEmail(targetEmail)],
    }),
    listeners(({ actions, values }) => ({
        openExitModal: () => {
            // Frontend-only event (no backend counterpart); the delegate/skip success events are fired from the backend.
            posthog.capture('onboarding exit modal opened', { step_at_open: values.stepKey || null })
        },
        submitDelegation: async () => {
            // Guard against double-submit from Enter-Enter or rapid button double-click. The
            // listener is re-entrant by default — a second dispatch would fire another POST
            // before the first settles.
            if (values.isSubmitting) {
                return
            }
            if (!values.canSubmitDelegation) {
                return
            }
            const orgId = organizationLogic.values.currentOrganizationId
            if (!orgId) {
                lemonToast.error("Couldn't find your current organization. Please refresh and try again.")
                return
            }
            actions.setIsSubmitting(true)
            let delegationCommitted = false
            try {
                await api.create<OrganizationInviteType>(`api/organizations/${orgId}/invites/delegate/`, {
                    target_email: values.targetEmail.trim(),
                    message: values.message.trim(),
                    step_at_delegation: values.stepKey || '',
                })
                delegationCommitted = true
                // Honest wording: 201 means the invite row is persisted, not that SMTP has delivered.
                lemonToast.success(`Invite created — we'll email ${values.targetEmail.trim()}`)

                // Seed the freshest user into userLogic BEFORE navigating, otherwise sceneLogic's
                // onboarding-redirect check reads stale state and bounces us straight back to /onboarding.
                // Guard this refresh separately — if it fails after the POST succeeded, the
                // delegation is still committed and the user just needs to refresh.
                try {
                    const freshUser = await api.get<UserType>('api/users/@me/')
                    actions.loadUserSuccess(freshUser)
                } catch {
                    // Fall back to a plain loadUser() for retry; sceneLogic will pick up the
                    // delegation state on the next render.
                    actions.loadUser()
                }

                actions.closeExitModal()
                router.actions.push(urls.default())
            } catch (error: any) {
                if (delegationCommitted) {
                    // POST succeeded but a follow-up step failed — don't show a scary error
                    // that would make the user re-submit into `existing_invite`.
                    actions.closeExitModal()
                    router.actions.push(urls.default())
                    return
                }
                lemonToast.error(extractErrorDetail(error, "Couldn't send the invitation. Please try again."))
            } finally {
                actions.setIsSubmitting(false)
            }
        },
        submitSkip: async () => {
            if (values.isSubmitting) {
                return
            }
            const userUuid = values.user?.uuid
            if (!userUuid) {
                lemonToast.error('Please refresh and try again.')
                return
            }
            actions.setIsSubmitting(true)
            try {
                const updatedUser = await api.create<UserType>(`api/users/${userUuid}/onboarding/skip/`, {
                    reason: 'later',
                    step_at_skip: values.stepKey || '',
                })
                // The skip endpoint returns the updated user — seed state directly so sceneLogic
                // sees the fresh suppression flags before the navigation evaluates the redirect.
                actions.loadUserSuccess(updatedUser)
                actions.closeExitModal()
                router.actions.push(urls.default())
            } catch (error: any) {
                lemonToast.error(extractErrorDetail(error, "Couldn't skip setup. Please try again."))
            } finally {
                actions.setIsSubmitting(false)
            }
        },
    })),
])
