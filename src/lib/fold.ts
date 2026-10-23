/** Minuscules sans accents, pour comparer « Élection » et « election ». */
export function fold(text: string): string {
  return text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}
