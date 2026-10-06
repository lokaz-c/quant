import type { DataLabel } from './api'

export type DataKind = 'real' | 'synthetic' | 'mixed'

export interface Banner {
  kind: DataKind
  title: string
  text: string
  /** One line for the footer */
  footer: string
  /** A word or two for the run history */
  short: string
}

/**
 * Real only when the bars came from market-data and the service labelled every
 * symbol alpaca. Decided here from the recorded sources, not from the server's
 * `synthetic` flag alone, so a run can't be shown as real unless both agree.
 */
export function dataKind(label: Pick<DataLabel, 'source' | 'reported_source' | 'synthetic'>): DataKind {
  if (label.source === 'market-data' && label.reported_source === 'alpaca' && label.synthetic === false) return 'real'
  if (label.source === 'market-data' && label.reported_source === 'mixed') return 'mixed'
  return 'synthetic'
}

export function banner(label: DataLabel): Banner {
  const kind = dataKind(label)
  if (kind === 'real') {
    return {
      kind,
      title: 'Market data.',
      text: `${label.description} Past results on one period are not a forecast.`,
      footer: 'Daily bars from Alpaca via the market-data service.',
      short: 'Alpaca',
    }
  }
  if (kind === 'mixed') {
    return {
      kind,
      title: 'Partly synthetic data.',
      text: `${label.description}`,
      footer: 'Some symbols in this run are synthetic.',
      short: 'Mixed',
    }
  }
  const fromService = label.source === 'market-data'
  return {
    kind,
    title: 'Synthetic data.',
    text: fromService
      ? `${label.description}`
      : `${label.description} Results describe one simulated path, not real markets.`,
    footer: fromService ? 'Synthetic prices from the market-data service.' : 'Synthetic prices only.',
    short: fromService ? 'Synthetic (service)' : 'Synthetic',
  }
}
