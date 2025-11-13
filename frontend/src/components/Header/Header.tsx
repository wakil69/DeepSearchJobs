import { useTranslation } from "react-i18next";
import Tabs from "./Tabs/Tabs";

export default function Header() {
  const { t, i18n } = useTranslation();

  const languages = [
    { code: "en", label: "EN" },
    { code: "fr", label: "FR" },
    { code: "es", label: "ES" }, 
    { code: "it", label: "IT" },
    { code: "de", label: "DE" },
    { code: "ar", label: "AR" },
  ];

  const handleLanguageChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const lang = e.target.value;
    i18n.changeLanguage(lang);
  };

  const currentLang = i18n.language.split("-")[0];

  return (
    <header className="bg-blue-dark text-white shadow-lg">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between px-4 py-4 space-y-3 sm:space-y-0">
        <div className="flex items-center space-x-3">
          <img
            src="/Play2PathWhite.png"
            alt="Play2Path Logo"
            className="h-16 w-auto object-contain"
          />
          <h1 className="text-2xl font-bold tracking-wide">
            <span className="text-yellow-300">DeepSearchJobs</span>
          </h1>
        </div>

        <div className="flex items-center space-x-4">
          <a
            href="https://www.play2path.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-yellow-300 font-semibold hover:text-white transition-colors duration-200"
          >
            {t("visitWebsite")}
          </a>

          <select
            onChange={handleLanguageChange}
            value={currentLang} // ✅ show the currently active language
            className="bg-yellow-300 text-blue-dark font-semibold rounded-md px-2 py-1 cursor-pointer focus:outline-none focus:ring-2 focus:ring-yellow-200"
          >
            {languages.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="bg-white text-blue-dark border-t border-yellow-300">
        <Tabs />
      </div>
    </header>
  );
}
