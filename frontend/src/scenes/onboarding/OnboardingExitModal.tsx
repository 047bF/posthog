import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonSegmentedButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { onboardingExitLogic } from './onboardingExitLogic'

export function OnboardingExitModal(): JSX.Element {
    const { isExitModalOpen, targetEmail, message, canSubmitDelegation, isSubmitting, tab } =
        useValues(onboardingExitLogic)
    const { closeExitModal, setTargetEmail, setMessage, submitDelegation, submitSkip, setTab } =
        useActions(onboardingExitLogic)

    // Track IME composition on the email input. SubmitEvent doesn't carry `isComposing`, so
    // we watch composition events directly — otherwise CJK users pressing Enter to confirm
    // a character would submit the form mid-composition.
    const isComposingRef = useRef(false)

    const onDelegateSubmit = (e: React.FormEvent): void => {
        e.preventDefault()
        if (isComposingRef.current) {
            return
        }
        submitDelegation()
    }

    const onLaterSubmit = (e: React.FormEvent): void => {
        e.preventDefault()
        submitSkip()
    }

    // Block all close paths while a submit is in flight so we can't race the in-flight POST
    // and leave the user with a committed delegation but a torn-down modal.
    const handleClose = (): void => {
        if (isSubmitting) {
            return
        }
        closeExitModal()
    }

    const showEmailValidationError = targetEmail.length > 0 && !canSubmitDelegation

    return (
        <LemonModal
            isOpen={isExitModalOpen}
            onClose={handleClose}
            closable={!isSubmitting}
            title="Need someone else to finish setup?"
            description="Invite a teammate to continue, or finish later from settings."
        >
            <div className="flex flex-col gap-4" data-attr="onboarding-exit-modal">
                <div className="flex flex-col gap-2">
                    <p className="m-0 text-xs text-secondary">Choose how to continue</p>
                    <LemonSegmentedButton
                        value={tab}
                        onChange={(newTab) => setTab(newTab)}
                        fullWidth
                        options={[
                            {
                                value: 'delegate',
                                label: 'Invite a teammate',
                                'data-attr': 'onboarding-exit-tab-delegate',
                            },
                            {
                                value: 'later',
                                label: 'Finish later',
                                'data-attr': 'onboarding-exit-tab-later',
                            },
                        ]}
                    />
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
                            status={showEmailValidationError ? 'danger' : 'default'}
                            placeholder="engineer@example.com"
                            data-attr="onboarding-exit-email-input"
                            onKeyDown={(e) => {
                                // KeyboardEvent.isComposing is the right place to read IME state —
                                // SubmitEvent doesn't carry it. Tracking here so the form submit
                                // handler can skip while the user is mid-composition.
                                isComposingRef.current = (e.nativeEvent as KeyboardEvent).isComposing
                            }}
                            onKeyUp={(e) => {
                                // Ensure composition state clears after IME confirmation.
                                isComposingRef.current = (e.nativeEvent as KeyboardEvent).isComposing
                            }}
                            onBlur={() => {
                                isComposingRef.current = false
                            }}
                        />
                        {showEmailValidationError ? (
                            <p className="m-0 text-xs text-danger">Enter a valid email address</p>
                        ) : null}
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
                            They'll be added as an admin so they can complete onboarding.
                        </p>
                        <div className="flex justify-end gap-2 mt-2">
                            <LemonButton
                                type="secondary"
                                onClick={handleClose}
                                htmlType="button"
                                disabledReason={isSubmitting ? 'Sending invitation…' : undefined}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isSubmitting}
                                disabledReason={!canSubmitDelegation ? 'Enter a valid email address' : undefined}
                                data-attr="onboarding-exit-send-invitation"
                            >
                                Send invitation
                            </LemonButton>
                        </div>
                    </form>
                )}

                {tab === 'later' && (
                    <form onSubmit={onLaterSubmit} className="flex flex-col gap-3">
                        <p className="m-0">You can finish setup anytime from settings.</p>
                        <div className="flex justify-end gap-2">
                            <LemonButton
                                type="secondary"
                                onClick={handleClose}
                                htmlType="button"
                                disabledReason={isSubmitting ? 'Skipping…' : undefined}
                            >
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
