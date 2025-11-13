import { useTranslation } from "react-i18next";

export default function TableJobsHeader() {
  const { t } = useTranslation();
  return (
    <thead className="bg-blue-dark text-white">
      <tr>
        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("jobTitle")}
        </th>
        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("company")}
        </th>
        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("country")}
        </th>
        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("region")}
        </th>
        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("contractType")}
        </th>
        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("salary")}
        </th>
        <th className="px-4 py-3 text-left text-sm font-semibold uppercase tracking-wide">
          {t("dateFetched")}
        </th>
        <th className="px-4 py-3 text-center text-sm font-semibold uppercase tracking-wide">
          {t("actions")}
        </th>
      </tr>
    </thead>
  );
}
