import { useActions } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { onboardingExitLogic } from './onboardingExitLogic'
import { OnboardingExitModal } from './OnboardingExitModal'

export function OnboardingExitAction(): JSX.Element {
    const { openExitModal } = useActions(onboardingExitLogic)

    return (
        <>
            <div className="mt-6 text-center">
                <Link onClick={openExitModal} data-attr="onboarding-exit-link" subtle>
                    I'm not the right person to set this up
                </Link>
            </div>
            <OnboardingExitModal />
        </>
    )
}
