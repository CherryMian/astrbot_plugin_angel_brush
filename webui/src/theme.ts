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
  return {
    common: {
      primaryColor: c.base,
      primaryColorHover: c.hover,
      primaryColorPressed: c.pressed,
      primaryColorSuppl: c.suppl,
      fontSize: '15px',
      borderRadius: '10px',
      borderRadiusSmall: '8px',
    },
    Button: {
      borderRadius: '999px',
    },
  }
}
