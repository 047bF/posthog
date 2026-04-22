import { env } from 'cloudflare:workers'
import { PostHog } from 'posthog-node'

import { CloudflareKVFlagCacheReader, isLocalEvalEnabled } from './flag-cache'

let _client: PostHog | undefined

export enum AnalyticsEvent {
    MCP_INIT = 'mcp init',
}

export const getPostHogClient = (): PostHog => {
    if (!_client) {
        _client = buildClient()
    }
    return _client
}

function buildClient(): PostHog {
    const disabled = !env.POSTHOG_ANALYTICS_API_KEY || !env.POSTHOG_ANALYTICS_HOST
    const baseOptions = {
        disabled,
        host: env.POSTHOG_ANALYTICS_HOST,
        flushAt: 1,
        flushInterval: 0,
    }

    if (!isLocalEvalEnabled(env as Env)) {
        return new PostHog(env.POSTHOG_ANALYTICS_API_KEY, baseOptions)
    }

    // Request-path client: reads flag definitions from the KV cache that the
    // scheduled cron refreshes. Local eval for anything it can decide,
    // posthog-node falls back to remote /flags for anything it can't.
    const e = env as unknown as Env
    const cache = new CloudflareKVFlagCacheReader(e.FLAG_DEFS_KV, env.POSTHOG_ANALYTICS_API_KEY)
    return new PostHog(env.POSTHOG_ANALYTICS_API_KEY, {
        ...baseOptions,
        personalApiKey: e.MCP_FLAG_LOCAL_EVAL_KEY,
        enableLocalEvaluation: true,
        flagDefinitionCacheProvider: cache,
    })
}

export async function isFeatureFlagEnabled(flagKey: string, distinctId: string): Promise<boolean> {
    try {
        const client = getPostHogClient()
        const result = await client.isFeatureEnabled(flagKey, distinctId)
        return result === true
    } catch {
        return false
    }
}

/**
 * Evaluate multiple feature flags in parallel for the given user.
 * Returns a map of flag key → boolean.
 */
export async function evaluateFeatureFlags(flagKeys: string[], distinctId: string): Promise<Record<string, boolean>> {
    if (flagKeys.length === 0) {
        return {}
    }

    const results = await Promise.all(
        flagKeys.map(async (key) => {
            const enabled = await isFeatureFlagEnabled(key, distinctId)
            return [key, enabled] as const
        })
    )

    return Object.fromEntries(results)
}
