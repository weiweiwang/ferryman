import { useState, useCallback } from 'react';
import en from '../locales/en.json';
import zh from '../locales/zh.json';

type Locale = 'en' | 'zh';
type Translations = typeof en;

const translations: Record<Locale, Translations> = { en, zh };

export function useI18n() {
  const [locale, setLocale] = useState<Locale>(() => {
    const saved = localStorage.getItem('ferryman_locale');
    if (saved) return saved as Locale;
    
    // Auto-detect browser language
    const browserLang = navigator.language.toLowerCase();
    return browserLang.startsWith('zh') ? 'zh' : 'en';
  });

  const t = useCallback((key: string) => {
    const keys = key.split('.');
    let value: any = translations[locale];
    
    for (const k of keys) {
      if (value && typeof value === 'object' && k in value) {
        value = value[k];
      } else {
        return key; // Fallback to key name
      }
    }
    
    return typeof value === 'string' ? value : key;
  }, [locale]);

  const changeLanguage = (newLocale: Locale) => {
    setLocale(newLocale);
    localStorage.setItem('ferryman_locale', newLocale);
  };

  return { t, locale, changeLanguage };
}
