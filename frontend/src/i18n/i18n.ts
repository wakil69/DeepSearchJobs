import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import detector from "i18next-browser-languagedetector";
import en from "./locales/en.json";
import fr from "./locales/fr.json";
import it from "./locales/it.json";
import es from "./locales/es.json";
import de from "./locales/de.json";
import ar from "./locales/ar.json";

i18n
  .use(detector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      fr: { translation: fr },
      it: { translation: it },
      es: { translation: es },
      ar: { translation: ar },
      de: { translation: de },
    },
    fallbackLng: "en",
    load: 'languageOnly',
    debug: import.meta.env.DEV,
    interpolation: {
      escapeValue: false,
    },
    detection: {
      lookupCookie: "i18next",
      lookupLocalStorage: "i18nextLng",
      order: ["cookie", "localStorage", "navigator", "htmlTag"],
      caches: ["cookie"],
      cookieMinutes: 60 * 24 * 365 * 20,
      cookieDomain: window.location.hostname,
      cookieOptions: { path: "/", sameSite: "strict" },
    },
  });

export default i18n;
