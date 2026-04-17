import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
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
        submitDelegation: true,
        submitSkip: true,
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
    }),
    selectors({
        canSubmitDelegation: [(s) => [s.targetEmail], (targetEmail) => isValidEmail(targetEmail)],
    }),
    loaders(() => ({
        delegationInvite: [
            null as OrganizationInviteType | null,
            {
                createDelegationInvite: async (payload: { target_email: string; message?: string; step?: string }) => {
                    const orgId = organizationLogic.values.currentOrganizationId
                    if (!orgId) {
                        throw new Error('Missing current organization.')
                    }
                    return await api.create<OrganizationInviteType>(`api/organizations/${orgId}/invites/delegate/`, {
                        target_email: payload.target_email,
                        message: payload.message ?? '',
                        step_at_delegation: payload.step ?? '',
                    })
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        openExitModal: () => {
            posthog.capture('onboarding exit modal opened', {
                step_at_open: values.stepKey || null,
            })
        },
        submitDelegation: async () => {
            if (!values.canSubmitDelegation) {
                return
            }
            try {
                const invite = await (actions as any).createDelegationInvite({
                    target_email: values.targetEmail.trim(),
                    message: values.message.trim() || undefined,
                    step: values.stepKey || undefined,
                })
                const domainPart = values.targetEmail.split('@')[1] || null
                posthog.capture('onboarding delegated', {
                    target_email_domain: domainPart,
                    has_message: Boolean(values.message.trim()),
                    step_at_delegation: values.stepKey || null,
                    invite_id: invite?.id ?? null,
                })
                lemonToast.success(`Invite sent to ${values.targetEmail.trim()}`)
                actions.closeExitModal()
                actions.loadUser()
                router.actions.push(urls.default())
            } catch (error: any) {
                const detail = error?.data?.detail || error?.detail || 'Could not send the delegation invite.'
                lemonToast.error(detail)
            }
        },
        submitSkip: async () => {
            try {
                await api.create(`api/users/@me/onboarding/skip/`, {
                    reason: 'later',
                    step_at_skip: values.stepKey || '',
                })
                posthog.capture('onboarding skipped later', { step_at_skip: values.stepKey || null })
                actions.closeExitModal()
                actions.loadUser()
                router.actions.push(urls.default())
            } catch (error: any) {
                const detail = error?.data?.detail || error?.detail || 'Could not skip onboarding.'
                lemonToast.error(detail)
            }
        },
    })),
])
