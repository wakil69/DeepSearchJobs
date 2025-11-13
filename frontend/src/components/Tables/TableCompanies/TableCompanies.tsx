import { useState, useMemo } from "react";
import TableCompaniesHeader from "./TableCompaniesHeader";
import TableCompaniesRow from "./TableCompaniesRow";
import ImportCompanies from "./Import/ImportCompanies";
import useGetCompanies from "../../../hooks/companies/useGetCompanies";
import { useDebounce } from "use-debounce";
import FilterCompanies from "./Filter/FilterCompanies";
import ActionCompanies from "./Actions/ActionsCompanies";
import Loader from "../../Loader/Loader";
import { Trans, useTranslation } from "react-i18next";

export default function TableCompanies() {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<number[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 10;

  const [debouncedSearch] = useDebounce(search, 500);

  const { companiesResponse, isFetchingCompanies, refetchCompanies } =
    useGetCompanies({
      page: currentPage,
      pageSize,
      search: debouncedSearch,
      statusFilter,
    });

  const currentCompanies = useMemo(() => {
    return companiesResponse?.companies || [];
  }, [companiesResponse]);

  const totalPages = useMemo(
    () => Math.ceil((companiesResponse?.total ?? 0) / pageSize),
    [companiesResponse]
  );

  const handlePrevPage = () => {
    setCurrentPage((prev) => Math.max(prev - 1, 1));
  };

  const handleNextPage = () => {
    setCurrentPage((prev) => Math.min(prev + 1, totalPages));
  };

  const allSelected = useMemo(
    () =>
      currentCompanies.length > 0 &&
      selected.length === currentCompanies.length,
    [currentCompanies, selected]
  );

  const handleToggleAll = (checked: boolean) => {
    setSelected(checked ? currentCompanies.map((c) => c.id) : []);
  };

  return (
    <div className="w-10/12 flex flex-col mx-auto my-10 bg-white shadow-md rounded-xl">
      <div className="w-full flex flex-col px-6 pt-6 gap-3">
        <h2 className="text-2xl font-bold text-blue-dark">{t("companies")}</h2>

        <ImportCompanies />

        <FilterCompanies
          search={search}
          setSearch={setSearch}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          setCurrentPage={setCurrentPage}
        />

        <ActionCompanies
          selected={selected}
          setSelected={setSelected}
          refetchCompanies={refetchCompanies}
          isFetchingCompanies={isFetchingCompanies}
        />
        <div className="space-y-4">
          <div className="p-4 bg-blue-50 border border-blue-200 rounded-2xl shadow-sm">
            <h3 className="text-blue-700 font-semibold text-lg mb-1">
              {t("launchAnalyseTitle")}
            </h3>
            <p className="text-gray-700 text-sm leading-relaxed">
              {t("launchAnalyseExplanation")}
            </p>
          </div>

          <div className="p-4 bg-green-50 border border-green-200 rounded-2xl shadow-sm">
            <h3 className="text-green-700 font-semibold text-lg mb-1">
              {t("launchCheckJobsTitle")}
            </h3>
            <p className="text-gray-700 text-sm leading-relaxed">
              {t("launchCheckJobsExplanation")}
            </p>
          </div>
        </div>
      </div>

      {isFetchingCompanies ? (
        <div className="flex items-center justify-center h-[500px]">
          <Loader />
        </div>
      ) : (
        <div className="overflow-x-auto mt-4 overflow-y-auto min-h-[600px]">
          <table className="min-w-full border-collapse">
            <TableCompaniesHeader
              key={allSelected ? "checked" : "unchecked"}
              allSelected={allSelected}
              onToggleAll={handleToggleAll}
            />
            <tbody>
              {currentCompanies.map((company) => (
                <TableCompaniesRow
                  key={company.id}
                  company={company}
                  isSelected={selected.includes(company.id)}
                  setSelected={setSelected}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between px-6 py-4 border-t bg-gray-50">
        <span className="text-sm text-gray-600">
          <Trans i18nKey="pageInfo" values={{ currentPage, totalPages }} />
        </span>

        <div className="flex gap-2">
          <button
            onClick={handlePrevPage}
            disabled={currentPage === 1}
            className={`px-3 py-1 rounded-md text-sm font-medium ${
              currentPage === 1
                ? "bg-gray-200 text-gray-500 cursor-not-allowed"
                : "bg-yellow-300 text-blue-dark hover:bg-yellow-400"
            }`}
          >
            {t("previous")}
          </button>

          <button
            onClick={handleNextPage}
            disabled={currentPage === totalPages}
            className={`px-3 py-1 rounded-md text-sm font-medium ${
              currentPage === totalPages
                ? "bg-gray-200 text-gray-500 cursor-not-allowed"
                : "bg-yellow-300 text-blue-dark hover:bg-yellow-400"
            }`}
          >
            {t("next")}
          </button>
        </div>
      </div>
    </div>
  );
}
