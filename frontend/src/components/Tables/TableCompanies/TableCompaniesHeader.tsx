import { useTranslation } from "react-i18next";

interface TableCompaniesHeaderProps {
  allSelected: boolean;
  onToggleAll: (selected: boolean) => void;
}

export default function TableCompaniesHeader({
  allSelected,
  onToggleAll,
}: TableCompaniesHeaderProps) {
  const { t } = useTranslation();

  return (
    <thead className="bg-blue-dark text-white sticky top-0 z-10">
      <tr>
        <th className="px-4 py-3 text-center">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={(e) => onToggleAll(e.target.checked)}
            className="w-4 h-4 accent-yellow-400 cursor-pointer"
          />
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("name")} 
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("website")}
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("internalCareerPages")}
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("internalCareerPages")}
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("externalCareerPages")}
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("nbOpportunities")}
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("lastCheckDate")}
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("status")}
        </th>

        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide"></th>
      </tr>
    </thead>
  );
}
