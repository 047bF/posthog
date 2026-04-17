import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { onboardingExitLogic } from './onboardingExitLogic'

type Tab = 'delegate' | 'later'

export function OnboardingExitModal(): JSX.Element {
    const { isExitModalOpen, targetEmail, message, canSubmitDelegation, delegationInviteLoading } =
        useValues(onboardingExitLogic)
    const { closeExitModal, setTargetEmail, setMessage, submitDelegation, submitSkip } = useActions(onboardingExitLogic)

    const [tab, setTab] = useState<Tab>('delegate')

    return (
        <LemonModal
            isOpen={isExitModalOpen}
            onClose={closeExitModal}
            title="Not the right person to set this up?"
            description="Hand off setup to a teammate, or come back to it later."
        >
            <div className="flex flex-col gap-4" data-attr="onboarding-exit-modal">
                <div className="flex gap-2">
                    <LemonButton
                        type={tab === 'delegate' ? 'primary' : 'secondary'}
                        onClick={() => setTab('delegate')}
                        data-attr="onboarding-exit-tab-delegate"
                    >
                        Invite a teammate
                    </LemonButton>
                    <LemonButton
                        type={tab === 'later' ? 'primary' : 'secondary'}
                        onClick={() => setTab('later')}
                        data-attr="onboarding-exit-tab-later"
                    >
                        I'll finish this later
                    </LemonButton>
                </div>

                <LemonDivider />

                {tab === 'delegate' && (
                    <div className="flex flex-col gap-2">
                        <label className="font-semibold" htmlFor="onboarding-exit-email">
                            Teammate's email
                        </label>
                        <LemonInput
                            id="onboarding-exit-email"
                            type="email"
                            autoFocus
                            value={targetEmail}
                            onChange={setTargetEmail}
                            placeholder="engineer@example.com"
                            data-attr="onboarding-exit-email-input"
                        />
                        <label className="font-semibold mt-2" htmlFor="onboarding-exit-message">
                            Personal message (optional)
                        </label>
                        <LemonTextArea
                            id="onboarding-exit-message"
                            value={message}
                            onChange={setMessage}
                            placeholder="Hey — can you get this set up? Thanks!"
                            data-attr="onboarding-exit-message-input"
                            minRows={3}
                        />
                        <div className="flex justify-end gap-2 mt-2">
                            <LemonButton type="secondary" onClick={closeExitModal}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                loading={delegationInviteLoading}
                                disabledReason={!canSubmitDelegation ? 'Enter a valid email address first' : undefined}
                                onClick={() => submitDelegation()}
                                data-attr="onboarding-exit-send-invitation"
                            >
                                Send invitation
                            </LemonButton>
                        </div>
                    </div>
                )}

                {tab === 'later' && (
                    <div className="flex flex-col gap-3">
                        <p className="m-0">You can finish setup anytime from Settings.</p>
                        <div className="flex justify-end gap-2">
                            <LemonButton type="secondary" onClick={closeExitModal}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => submitSkip()}
                                data-attr="onboarding-exit-skip-for-now"
                            >
                                Skip for now
                            </LemonButton>
                        </div>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
