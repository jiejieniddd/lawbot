import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type ThemeMode = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'careerbot-theme'

function readStoredTheme(): ThemeMode | null {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY)
    if (raw === 'light' || raw === 'dark') return raw
  } catch {
    /* ignore */
  }
  return null
}

function detectPreferredTheme(): ThemeMode {
  if (typeof window !== 'undefined' && window.matchMedia) {
    if (window.matchMedia('(prefers-color-scheme: light)').matches) return 'light'
  }
  return 'dark'
}

export function resolveInitialTheme(): ThemeMode {
  return readStoredTheme() ?? detectPreferredTheme()
}

export function applyThemeToDom(theme: ThemeMode) {
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  root.classList.toggle('dark', theme === 'dark')
}

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<ThemeMode>(resolveInitialTheme())
  const isLight = computed(() => theme.value === 'light')

  function persist(next: ThemeMode) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
  }

  function setTheme(next: ThemeMode) {
    theme.value = next
    applyThemeToDom(next)
    persist(next)
  }

  function setLight(checked: boolean) {
    setTheme(checked ? 'light' : 'dark')
  }

  function toggle() {
    setLight(!isLight.value)
  }

  function initTheme() {
    const next = resolveInitialTheme()
    theme.value = next
    applyThemeToDom(next)
  }

  return { theme, isLight, setTheme, setLight, toggle, initTheme }
})
