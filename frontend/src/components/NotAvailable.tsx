import type { UndefinedMetrics } from '../api'

export const NOT_AVAILABLE = 'n/a'

/** The reason the API gave for a null metric */
export function reasonFor(undefinedMetrics: UndefinedMetrics | null | undefined, key: string): string {
  return undefinedMetrics?.[key] ?? 'undefined for this run'
}

/** A metric that is undefined for the run: "n/a", with the reason on hover and for screen readers */
export function NotAvailable({ reason }: { reason: string }) {
  return (
    <abbr className="na" title={`Not available: ${reason}`}>
      {NOT_AVAILABLE}
    </abbr>
  )
}
