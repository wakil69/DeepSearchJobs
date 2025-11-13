import { useTranslation } from "react-i18next";

export default function FilterCompanies({
  search,
  setSearch,
  statusFilter,
  setStatusFilter,
  setCurrentPage,
}: {
  search: string;
  setSearch: (value: string) => void;
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  setCurrentPage: (value: number) => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between mt-4 gap-3">
      <input
        type="text"
        placeholder={t("search")}
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setCurrentPage(1); // reset to first page on search
        }}
        className="w-full sm:w-1/2 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-yellow-300"
      />

      <select
        value={statusFilter}
        onChange={(e) => {
          setStatusFilter(e.target.value);
          setCurrentPage(1);
        }}
        className="w-full sm:w-1/4 px-3 py-2 border border-gray-300 rounded-md bg-white text-blue-dark font-medium focus:outline-none focus:ring-2 focus:ring-yellow-300"
      >
        <option value="">{t("allStatuses")}</option>
        <option value="queued">{t("queued")}</option>
        <option value="in_progress">{t("inProgress")}</option>
        <option value="done">{t("done")}</option>
        <option value="failed">{t("failed")}</option>
        <option value="idle">{t("idle")}</option>
      </select>
    </div>
  );
}
