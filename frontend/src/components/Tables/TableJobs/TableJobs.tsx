import { useState, useMemo } from "react";
import TableJobsHeader from "./TableJobsHeader";
import TableJobsRow from "./TableJobsRow";
import useGetJobs from "../../../hooks/jobs/useGetJobs";
import FiltersJobs from "./Filters/FiltersJobs";
import useGetAllCompanies from "../../../hooks/jobs/useGetAllCompanies";
import type { ContractType } from "../../../types/jobs";
import useGetJobsAppliedOrNotInterested from "../../../hooks/jobs/useGetJobsAppliedOrNotInterested";
import Loader from "../../Loader/Loader";
import { useDebounce } from "use-debounce";
import { Trans, useTranslation } from "react-i18next";

export default function TableJobs() {
  const { t } = useTranslation();

  const [selectedCountry, setSelectedCountry] = useState<string | undefined>(
    undefined
  );
  const [search, setSearch] = useState<string | undefined>(undefined);
  const [regionsSelected, setSelectedRegions] = useState<string[] | undefined>(
    undefined
  );
  const [contractTypeSelected, setSelectedContractType] = useState<
    ContractType | undefined
  >(undefined);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [selectedCompany, setSelectedCompany] = useState<number | undefined>(
    undefined
  );
  const itemsPerPage = 10;
  const status: "applied" | "not_interested" | undefined = useMemo(() => {
    if (location.pathname.includes("/applied-jobs")) return "applied";
    if (location.pathname.includes("/not-interested-jobs"))
      return "not_interested";
    return undefined;
  }, [location.pathname]);

  const [debouncedSearch] = useDebounce(search, 500);

  const { allCompanies } = useGetAllCompanies();

  const params = useMemo(
    () => ({
      page: currentPage,
      pageSize: itemsPerPage,
      country: selectedCountry,
      regions: regionsSelected,
      contract_type: contractTypeSelected,
      company_id: selectedCompany,
      status,
      search: debouncedSearch,
    }),
    [
      currentPage,
      itemsPerPage,
      selectedCountry,
      regionsSelected,
      contractTypeSelected,
      selectedCompany,
      status,
      debouncedSearch,
    ]
  );

  const { jobsProposals, isFetchingJobsProposals } = useGetJobs(params);

  const { jobsAppliedOrNotInterested, isFetchingJobsAppliedOrNotInterested } =
    useGetJobsAppliedOrNotInterested(params);

  const jobs = status ? jobsAppliedOrNotInterested : jobsProposals;

  const isFetchingJobs = status
    ? isFetchingJobsAppliedOrNotInterested
    : isFetchingJobsProposals;

  const totalPages = Math.ceil((jobs?.total ?? 0) / itemsPerPage);

  const handlePrevPage = () => {
    setCurrentPage((prev) => Math.max(prev - 1, 1));
  };

  const handleNextPage = () => {
    setCurrentPage((prev) => Math.min(prev + 1, totalPages));
  };

  return (
    <div className="w-10/12 mx-auto my-10 bg-white shadow-md rounded-xl overflow-x-scroll">
      <h2 className="text-2xl font-bold text-blue-dark px-6 pt-6">
        {t("jobs")}
      </h2>

      <FiltersJobs
        key={allCompanies?.length ?? 0}
        allCompanies={allCompanies}
        selectedCountry={selectedCountry}
        setSelectedRegions={setSelectedRegions}
        setSelectedCountry={setSelectedCountry}
        selectedCompany={selectedCompany}
        search={search}
        setSelectedCompany={setSelectedCompany}
        contractTypeSelected={contractTypeSelected}
        regionsSelected={regionsSelected}
        setSelectedContractType={setSelectedContractType}
        setCurrentPage={setCurrentPage}
        setSearch={setSearch}
      />

      {/* Table */}
      <div className="overflow-x-auto mt-4 overflow-y-auto min-h-[600px]">
        {isFetchingJobs ? (
          <div className="flex items-center justify-center h-[500px]">
            <Loader />
          </div>
        ) : (
          <table className="min-w-full border-collapse">
            <TableJobsHeader />
            <tbody>
              {jobs && jobs.jobs.length > 0 ? (
                jobs.jobs.map((job) => <TableJobsRow key={job.id} job={job} />)
              ) : (
                <tr>
                  <td
                    colSpan={7}
                    className="text-center py-6 text-gray-500 italic"
                  >
                    {t("noJobsFound")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
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
