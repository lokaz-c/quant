const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const money2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const plain = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 })

export const dash = '–'

export function formatMoney(value: number | null | undefined, cents = false): string {
  if (value == null) return dash
  return (cents ? money2 : money).format(value)
}

/** A value already in percent: 12.345 -> "12.35%" */
export function formatPct(value: number | null | undefined, digits = 2): string {
  return value == null ? dash : `${value.toFixed(digits)}%`
}

/** A fraction: 0.15 -> "15%" (risk-profile limits) */
export function formatFraction(value: number | null | undefined): string {
  return value == null ? dash : `${plain.format(value * 100)}%`
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  return value == null ? dash : value.toFixed(digits)
}

/** 1.234 -> "+1.23", -1.234 -> "-1.23"; anything that rounds to zero -> "0.00" */
export function formatSigned(value: number | null | undefined, digits = 2): string {
  if (value == null) return dash
  if (Math.abs(value) < 0.5 * 10 ** -digits) return (0).toFixed(digits)
  return value > 0 ? `+${value.toFixed(digits)}` : value.toFixed(digits)
}

export function formatQuantity(value: number): string {
  return plain.format(value)
}

/** "2023-01-03" -> "Jan 2023" for chart ticks */
export function formatMonth(date: string): string {
  const [year, month] = date.split('-')
  const name = new Date(Date.UTC(Number(year), Number(month) - 1, 1)).toLocaleString('en-US', {
    month: 'short',
    timeZone: 'UTC',
  })
  return `${name} ${year}`
}
