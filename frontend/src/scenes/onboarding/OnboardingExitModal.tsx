import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { onboardingExitLogic } from './onboardingExitLogic'

export function OnboardingExitModal(): JSX.Element {
    const { isExitModalOpen, targetEmail, message, canSubmitDelegation, isSubmitting, tab } =
        useValues(onboardingExitLogic)
    const { closeExitModal, setTargetEmail, setMessage, submitDelegation, submitSkip, setTab } =
        useActions(onboardingExitLogic)

    const onDelegateSubmit = (e: React.FormEvent): void => {
        e.preventDefault()
        // Skip submit while the user is mid-composition on an IME (e.g. CJK input methods).
        if ((e.nativeEvent as any)?.isComposing) {
            return
        }
        submitDelegation()
    }

    const onLaterSubmit = (e: React.FormEvent): void => {
        e.preventDefault()
        if ((e.nativeEvent as any)?.isComposing) {
            return
        }
        submitSkip()
    }

    return (
        <LemonModal
            isOpen={isExitModalOpen}
            onClose={closeExitModal}
            title="Not the right person to set this up?"
            description="Hand off setup to a teammate, or come back to it later."
        >
            <div className="flex flex-col gap-4" data-attr="onboarding-exit-modal">
                <div role="tablist" aria-label="Onboarding exit options" className="flex gap-2">
                    <LemonButton
                        role="tab"
                        aria-selected={tab === 'delegate'}
                        type={tab === 'delegate' ? 'primary' : 'secondary'}
                        onClick={() => setTab('delegate')}
                        data-attr="onboarding-exit-tab-delegate"
                    >
                        Invite a teammate
                    </LemonButton>
                    <LemonButton
                        role="tab"
                        aria-selected={tab === 'later'}
                        type={tab === 'later' ? 'primary' : 'secondary'}
                        onClick={() => setTab('later')}
                        data-attr="onboarding-exit-tab-later"
                    >
                        Finish later
                    </LemonButton>
                </div>

                <LemonDivider />

                {tab === 'delegate' && (
                    <form onSubmit={onDelegateSubmit} className="flex flex-col gap-2">
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
                        <p className="text-secondary text-xs m-0 mt-1">
                            Your teammate will be invited as an admin so they can finish setup.
                        </p>
                        <div className="flex justify-end gap-2 mt-2">
                            <LemonButton type="secondary" onClick={closeExitModal} htmlType="button">
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isSubmitting}
                                disabledReason={!canSubmitDelegation ? 'Enter a valid email address first' : undefined}
                                data-attr="onboarding-exit-send-invitation"
                            >
                                Send invitation
                            </LemonButton>
                        </div>
                    </form>
                )}

                {tab === 'later' && (
                    <form onSubmit={onLaterSubmit} className="flex flex-col gap-3">
                        <p className="m-0">You can finish setup anytime from your settings.</p>
                        <div className="flex justify-end gap-2">
                            <LemonButton type="secondary" onClick={closeExitModal} htmlType="button">
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isSubmitting}
                                data-attr="onboarding-exit-skip-for-now"
                            >
                                Skip for now
                            </LemonButton>
                        </div>
                    </form>
                )}
            </div>
        </LemonModal>
    )
}
