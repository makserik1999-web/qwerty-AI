/**
 * A Kazakhstan mobile number, as it is typed.
 *
 * The field holds "+7 " and then at most ten digits, grouped the way the
 * number is read aloud: +7 707 123 45 67. Letters, an eleventh digit and a
 * second country code never make it into the field, so what is sent is either
 * a whole number or a half-typed one the button refuses. The server checks the
 * same rule again (77 and nine digits); this is for the person typing.
 */

const LOCAL_DIGITS = 10

/** The digits after +7 in what the field now holds. Typing past the tenth
 *  digit is ignored rather than shifting the number along. */
export function localDigits(raw: string): string {
  let digits = raw.replace(/\D/g, '')
  if (raw.trim().startsWith('+')) {
    // The field's own "+7".
    if (digits.startsWith('7')) digits = digits.slice(1)
  } else if (digits.length === LOCAL_DIGITS + 1 && /^[78]/.test(digits)) {
    // Filled in whole by the browser as 8 707 ... or 7 707 ...
    digits = digits.slice(1)
  }
  // The habit of dialling 8 first. No mobile code starts with 8, so after
  // "+7 " it can only be that, and it is dropped instead of becoming the number.
  if (digits.startsWith('8')) digits = digits.slice(1)
  return digits.slice(0, LOCAL_DIGITS)
}

/** The digits after +7 in a pasted number, whichever way it was written:
 *  +7 707 123 45 67, 8 (707) 123-45-67, 87071234567, 707 123 4567. */
export function pastedDigits(text: string): string {
  let digits = text.replace(/\D/g, '')
  if (digits.length > LOCAL_DIGITS && /^[78]/.test(digits)) digits = digits.slice(1)
  if (digits.startsWith('8')) digits = digits.slice(1)
  return digits.slice(0, LOCAL_DIGITS)
}

/** "+7 707 123 45 67", or as much of it as there is. */
export function formatLocal(digits: string): string {
  const groups = [digits.slice(0, 3), digits.slice(3, 6), digits.slice(6, 8), digits.slice(8, 10)]
  return `+7 ${groups.filter(Boolean).join(' ')}`
}

export const formatPhone = (raw: string): string => formatLocal(localDigits(raw))

/** A whole mobile number: ten digits, and mobile codes in Kazakhstan start with 7. */
export function isKzMobile(raw: string): boolean {
  return /^7\d{9}$/.test(localDigits(raw))
}

/** Typed far enough to know it is not a mobile: the operator code must start with 7. */
export function looksWrong(raw: string): boolean {
  const digits = localDigits(raw)
  return digits.length > 0 && !digits.startsWith('7')
}
