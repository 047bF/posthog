import { env } from 'cloudflare:workers'
import { PostHog } from 'posthog-node'

import { getFlagDefinitions, isLocalEvalEnabled } from './flag-cache'
import { evaluateFlagLocally } from './local-flag-evaluation'

let _client: PostHog | undefined

export enum AnalyticsEvent {
    MCP_INIT = 'mcp init',
}

export type FlagEvalCtx = { waitUntil: (p: Promise<unknown>) => void }

export const getPostHogClient = (): PostHog => {
    if (!_client) {
        _client = new PostHog(env.POSTHOG_ANALYTICS_API_KEY, {
            disabled: !env.POSTHOG_ANALYTICS_API_KEY || !env.POSTHOG_ANALYTICS_HOST, // Disable if the API key or host is not set
            host: env.POSTHOG_ANALYTICS_HOST,
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}

export async function isFeatureFlagEnabled(flagKey: string, distinctId: string, ctx?: FlagEvalCtx): Promise<boolean> {
    const local = await tryLocalEvaluation(flagKey, distinctId, ctx)
    if (local !== undefined) {
        return local
    }
    try {
        const client = getPostHogClient()
        const result = await client.isFeatureEnabled(flagKey, distinctId)
        return result === true
    } catch {
        return false
    }
}

/**
 * Evaluate multiple feature flags for the given user.
 * Loads the KV flag-defs snapshot once, evaluates what it can locally,
 * and fans out only undecided flags to remote in parallel.
 * Returns a map of flag key → boolean.
 */
export async function evaluateFeatureFlags(
    flagKeys: string[],
    distinctId: string,
    ctx?: FlagEvalCtx
): Promise<Record<string, boolean>> {
    if (flagKeys.length === 0) {
        return {}
    }

    const snapshot = isLocalEvalEnabled(env as Env) ? await getFlagDefinitions(env as Env, ctx) : null

    const out: Record<string, boolean> = {}
    const undecided: string[] = []

    for (const key of flagKeys) {
        if (snapshot) {
            const local = await evaluateFlagLocally(snapshot, key, distinctId)
            if (local !== undefined) {
                out[key] = local
                continue
            }
            sampleLog(key, 'unsupported')
        }
        undecided.push(key)
    }

    if (undecided.length > 0) {
        const client = getPostHogClient()
        const results = await Promise.all(
            undecided.map(async (key) => {
                try {
                    const r = await client.isFeatureEnabled(key, distinctId)
                    return [key, r === true] as const
                } catch {
                    return [key, false] as const
                }
            })
        )
        for (const [key, value] of results) {
            out[key] = value
        }
    }

    return out
}

async function tryLocalEvaluation(
    flagKey: string,
    distinctId: string,
    ctx?: FlagEvalCtx
): Promise<boolean | undefined> {
    if (!isLocalEvalEnabled(env as Env)) {
        return undefined
    }
    try {
        const snapshot = await getFlagDefinitions(env as Env, ctx)
        if (!snapshot) {
            sampleLog(flagKey, 'kv_miss')
            return undefined
        }
        const result = await evaluateFlagLocally(snapshot, flagKey, distinctId)
        if (result === undefined) {
            sampleLog(flagKey, 'unsupported')
        }
        return result
    } catch (error) {
        sampleLog(flagKey, 'error', error instanceof Error ? error.message : String(error))
        return undefined
    }
}

// 1% sample rate so logs don't drown us; still enough signal to spot regressions.
function sampleLog(flagKey: string, reason: string, detail?: string): void {
    if (Math.random() >= 0.01) {
        return
    }
    console.info('[flag-eval-fallthrough]', JSON.stringify({ flagKey, reason, ...(detail ? { detail } : {}) }))
}
