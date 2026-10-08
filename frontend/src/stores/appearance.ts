import { computed, ref } from 'vue'

export type Appearance = 'light' | 'dark' | 'system'
const preference = ref<Appearance>('light')
const systemDark = ref(false)
const resolved = computed(() =>
  preference.value === 'system' ? (systemDark.value ? 'dark' : 'light') : preference.value,
)
function apply() {
  document.documentElement.dataset.theme = resolved.value
}
export function setAppearance(value: Appearance) {
  preference.value = value
  try {
    localStorage.setItem('slothy.appearance', value)
  } catch {
    /* UI preferences may be unavailable in a restricted webview. */
  }
  apply()
}
export function initializeAppearance() {
  try {
    const saved = localStorage.getItem('slothy.appearance')
    if (saved === 'light' || saved === 'dark' || saved === 'system') preference.value = saved
  } catch {
    /* Use the documented light theme. */
  }
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  systemDark.value = media.matches
  media.addEventListener('change', (event) => {
    systemDark.value = event.matches
    apply()
  })
  apply()
}
export function useAppearance() {
  return { preference, resolved, setAppearance }
}
