import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { OrganizationInviteType } from '~/types'

import type { onboardingExitLogicType } from './onboardingExitLogicType'
import { onboardingLogic } from './onboardingLogic'

export type ExitReason = 'delegated' | 'later' | 'other'
export type ExitTab = 'delegate' | 'later'

const isValidEmail = (email: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())

export const onboardingExitLogic = kea<onboardingExitLogicType>([
    path(['scenes', 'onboarding', 'onboardingExitLogic']),
    connect(() => ({
        values: [onboardingLogic, ['stepKey'], userLogic, ['user']],
        actions: [userLogic, ['loadUser']],
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
            if (!values.canSubmitDelegation) {
                return
            }
            const orgId = organizationLogic.values.currentOrganizationId
            if (!orgId) {
                lemonToast.error('Missing current organization.')
                return
            }
            actions.setIsSubmitting(true)
            try {
                await api.create<OrganizationInviteType>(`api/organizations/${orgId}/invites/delegate/`, {
                    target_email: values.targetEmail.trim(),
                    message: values.message.trim(),
                    step_at_delegation: values.stepKey || '',
                })
                lemonToast.success(`Invite sent to ${values.targetEmail.trim()}`)
                actions.closeExitModal()
                actions.loadUser()
                router.actions.push(urls.default())
            } catch (error: any) {
                const detail = error?.data?.detail || error?.detail || 'Could not send the delegation invite.'
                lemonToast.error(detail)
            } finally {
                actions.setIsSubmitting(false)
            }
        },
        submitSkip: async () => {
            actions.setIsSubmitting(true)
            try {
                await api.create(`api/users/@me/onboarding/skip/`, {
                    reason: 'later',
                    step_at_skip: values.stepKey || '',
                })
                actions.closeExitModal()
                actions.loadUser()
                router.actions.push(urls.default())
            } catch (error: any) {
                const detail = error?.data?.detail || error?.detail || 'Could not skip onboarding.'
                lemonToast.error(detail)
            } finally {
                actions.setIsSubmitting(false)
            }
        },
    })),
])
