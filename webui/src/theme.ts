/**
 * 全局主题系统：以 iOS 26 Liquid Glass 为基准。
 * 拷贝自 angel_heart，仅 storage key 改为 brush 独立。
 */
import type { GlobalThemeOverrides } from 'naive-ui'
import type { ComputedRef, InjectionKey, Ref } from 'vue'
import { computed, ref } from 'vue'

export type ThemeMode = 'light' | 'dark'

const THEME_STORAGE_KEY = 'angel-brush-theme'

export interface ThemeApi {
  mode: Ref<ThemeMode>
  isDark: ComputedRef<boolean>
  toggle: () => void
}

export const themeKey: InjectionKey<ThemeApi> = Symbol('app-theme')

export function loadThemeMode(): ThemeMode {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

function saveThemeMode(mode: ThemeMode) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    /* 忽略持久化失败 */
  }
}

export function createThemeApi(): ThemeApi {
  const mode = ref<ThemeMode>(loadThemeMode())
  return {
    mode,
    isDark: computed(() => mode.value === 'dark'),
    toggle: () => {
      mode.value = mode.value === 'light' ? 'dark' : 'light'
      saveThemeMode(mode.value)
    },
  }
}

const brand = {
  light: { base: '#007aff', hover: '#3395ff', pressed: '#0062cc', suppl: '#3395ff' },
  dark: { base: '#0a84ff', hover: '#409cff', pressed: '#0069cc', suppl: '#409cff' },
}

export function buildThemeOverrides(mode: ThemeMode): GlobalThemeOverrides {
  const c = brand[mode]
  const glassCard = mode === 'light' ? 'rgba(255, 255, 255, 0.88)' : 'rgba(44, 44, 46, 0.85)'
  const btnGlass =
    mode === 'light'
      ? {
          color: 'rgba(255, 255, 255, 0.55)',
          colorHover: 'rgba(255, 255, 255, 0.78)',
          colorPressed: 'rgba(255, 255, 255, 0.5)',
          colorFocus: 'rgba(255, 255, 255, 0.55)',
          border: '1px solid rgba(255, 255, 255, 0.65)',
          borderHover: '1px solid rgba(255, 255, 255, 0.95)',
          borderPressed: '1px solid rgba(255, 255, 255, 0.5)',
          borderFocus: '1px solid rgba(255, 255, 255, 0.65)',
        }
      : {
          color: 'rgba(44, 44, 46, 0.5)',
          colorHover: 'rgba(72, 72, 76, 0.62)',
          colorPressed: 'rgba(40, 40, 42, 0.55)',
          colorFocus: 'rgba(44, 44, 46, 0.5)',
          border: '1px solid rgba(255, 255, 255, 0.14)',
          borderHover: '1px solid rgba(255, 255, 255, 0.28)',
          borderPressed: '1px solid rgba(255, 255, 255, 0.12)',
          borderFocus: '1px solid rgba(255, 255, 255, 0.14)',
        }
  return {
    common: {
      primaryColor: c.base,
      primaryColorHover: c.hover,
      primaryColorPressed: c.pressed,
      primaryColorSuppl: c.suppl,
      borderRadius: '10px',
      borderRadiusSmall: '8px',
      cardColor: glassCard,
    },
    Button: {
      borderRadius: '999px',
      ...btnGlass,
    },
    Layout: {
      color: 'transparent',
      siderColor: 'transparent',
      headerColor: 'transparent',
      footerColor: 'transparent',
    },
    Menu: {
      color: 'transparent',
    },
    Card: {
      colorEmbedded: glassCard,
    },
  }
}
