import { describe, expect, it } from 'vitest'
import type { DataLabel } from './api'
import { banner, dataKind } from './dataLabel'
import { alpaca, localSynthetic, mixed, serviceSynthetic } from './test/fixtures'

describe('dataKind', () => {
  it('is real only for market-data bars the service labelled alpaca', () => {
    expect(dataKind(alpaca)).toBe('real')
    expect(dataKind(localSynthetic)).toBe('synthetic')
    expect(dataKind(serviceSynthetic)).toBe('synthetic')
    expect(dataKind(mixed)).toBe('mixed')
  })

  it('falls back to synthetic whenever the fields disagree or are unknown', () => {
    expect(dataKind({ ...alpaca, synthetic: true })).toBe('synthetic')
    expect(dataKind({ ...alpaca, source: 'synthetic' })).toBe('synthetic')
    expect(dataKind({ ...serviceSynthetic, synthetic: false })).toBe('synthetic')
    expect(dataKind({ ...alpaca, reported_source: 'polygon' } as unknown as DataLabel)).toBe('synthetic')
  })
})

describe('banner', () => {
  it('words each kind differently', () => {
    expect(banner(localSynthetic)).toMatchObject({ title: 'Synthetic data.', footer: 'Synthetic prices only.', short: 'Synthetic' })
    expect(banner(localSynthetic).text).toContain('one simulated path')
    expect(banner(serviceSynthetic)).toMatchObject({ title: 'Synthetic data.', short: 'Synthetic (service)' })
    expect(banner(serviceSynthetic).text).toContain('source=synthetic')
    expect(banner(alpaca)).toMatchObject({ kind: 'real', title: 'Market data.', short: 'Alpaca' })
    expect(banner(mixed)).toMatchObject({ kind: 'mixed', title: 'Partly synthetic data.', short: 'Mixed' })
  })
})
