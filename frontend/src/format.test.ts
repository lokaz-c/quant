import { describe, expect, it } from 'vitest'
import { formatFraction, formatMoney, formatMonth, formatPct, formatSigned } from './format'

describe('formatters', () => {
  it('formats percentages, fractions, money and signed changes', () => {
    expect(formatPct(5.0916)).toBe('5.09%')
    expect(formatPct(null)).toBe('–')
    expect(formatFraction(0.15)).toBe('15%')
    expect(formatMoney(116940.4)).toBe('$116,940')
    expect(formatMoney(187.4249, true)).toBe('$187.42')
    expect(formatSigned(15.4412)).toBe('+15.44')
    expect(formatSigned(-15.151)).toBe('-15.15')
    expect(formatSigned(-0.001)).toBe('0.00')
    expect(formatSigned(3, 0)).toBe('+3')
  })

  it('labels chart ticks by month in UTC', () => {
    expect(formatMonth('2023-01-03')).toBe('Jan 2023')
    expect(formatMonth('2024-12-31')).toBe('Dec 2024')
  })
})
