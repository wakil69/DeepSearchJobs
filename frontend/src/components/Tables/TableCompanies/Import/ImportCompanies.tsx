import { Sheet } from "lucide-react";
import useImportCompanies from "../../../../hooks/companies/useImportCompanies";
import { useTranslation } from "react-i18next";

export default function ImportCompanies() {
  const { t } = useTranslation()
  const {
    mutateImportCompanies,
    isPendingImportCompanies,
    isSuccessImportCompanies,
    isErrorImportCompanies,
    message,
  } = useImportCompanies();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    if (selectedFile) {
      mutateImportCompanies(selectedFile); 
      e.target.value = "";
    }
  };

  return (
    <div className="flex flex-col gap-3 items-start">
      {/* Excel-styled import button */}
      <label
        htmlFor="file-upload"
        className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold 
          transition-all cursor-pointer
          ${
            isPendingImportCompanies
              ? "bg-gray-400 cursor-not-allowed text-white"
              : "bg-blue-900 hover:bg-yellow-300 hover:text-blue-900 text-white"
          }`}
      >
        <Sheet  className="w-5 h-5" />
        {isPendingImportCompanies ? t("importing") : t("importCsv") }
      </label>

      <input
        id="file-upload"
        type="file"
        accept=".csv, .xlsx"
        disabled={isPendingImportCompanies}
        onChange={handleFileChange}
        className="hidden"
      />

      {isSuccessImportCompanies && (
        <p className="text-green-600 font-semibold">{message}</p>
      )}
      {isErrorImportCompanies && (
        <p className="text-red-600 font-semibold">{message}</p>
      )}
    </div>
  );
}
