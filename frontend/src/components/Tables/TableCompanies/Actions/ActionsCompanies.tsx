import { useState, type Dispatch, type SetStateAction } from "react";
import DeleteModal from "./DeleteModal";
import useAnalyseCompanies from "../../../../hooks/companies/useAnalyseCompanies";
import Loader from "../../../Loader/Loader";
import type { CompaniesResponse } from "../../../../types/companies";
import type {
  QueryObserverResult,
  RefetchOptions,
} from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";
import { t } from "i18next";

export default function ActionCompanies({
  selected,
  setSelected,
  refetchCompanies,
  isFetchingCompanies,
}: {
  selected: number[];
  setSelected: Dispatch<SetStateAction<number[]>>;
  refetchCompanies: (
    options?: RefetchOptions | undefined
  ) => Promise<QueryObserverResult<CompaniesResponse, Error>>;
  isFetchingCompanies: boolean;
}) {
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  const handleGroupAction = (action: string) => {
    if (selected.length === 0) {
      alert("No companies selected.");
      return;
    }

    if (action === "Delete") {
      setShowDeleteModal(true);
    }

    if (action === "Launch Analyse") {
      mutateAnalyseCompanies({ ids: selected, type: "analyse" });
    }

    if (action === "Check Jobs") {
      mutateAnalyseCompanies({ ids: selected, type: "check" });
    }
  };

  const {
    mutateAnalyseCompanies,
    isPendingAnalyseCompanies,
    isErrorAnalyseCompanies,
    isSuccessAnalyseCompanies,
    message,
  } = useAnalyseCompanies(setSelected);

  const isDisabled = isFetchingCompanies || isPendingAnalyseCompanies;

  return (
    <>
      <div className="flex items-center justify-end gap-2 mt-4">
        <button
          onClick={() => handleGroupAction("Delete")}
          disabled={isDisabled}
          className="cursor-pointer bg-red-500 text-white px-3 py-1 rounded-md shadow-md shadow-black/40 hover:bg-red-600"
        >
          {t("delete")}
        </button>
        <button
          onClick={() => handleGroupAction("Launch Analyse")}
          disabled={isDisabled}
          className="cursor-pointer bg-blue-600 text-white px-3 py-1 rounded-md shadow-md shadow-black/40 hover:bg-blue-700"
        >
          {t("launchAnalyseTitle")}
        </button>
        <button
          onClick={() => handleGroupAction("Check Jobs")}
          disabled={isDisabled}
          className="cursor-pointer bg-green-600 text-white px-3 py-1 rounded-md shadow-md shadow-black/40 hover:bg-green-700"
        >
          {t("launchCheckJobsTitle")}
        </button>
        <button
          onClick={() => refetchCompanies()}
          disabled={isDisabled}
          className="cursor-pointer bg-blue-dark text-white px-3 py-1 rounded-md shadow-md shadow-black/40 hover:bg-blue-dark"
        >
          <RefreshCcw className="w-8 h-8" />
        </button>
      </div>
      {isPendingAnalyseCompanies && <Loader />}
      {showDeleteModal && (
        <DeleteModal
          selected={selected}
          setShowModal={setShowDeleteModal}
          setSelected={setSelected}
        />
      )}
      {isSuccessAnalyseCompanies && (
        <p className="text-green-600 font-semibold">{message}</p>
      )}
      {isErrorAnalyseCompanies && (
        <p className="text-red-600 font-semibold">{message}</p>
      )}
    </>
  );
}
