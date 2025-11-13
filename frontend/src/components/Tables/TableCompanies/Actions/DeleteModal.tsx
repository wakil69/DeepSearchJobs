import type { Dispatch, SetStateAction } from "react";
import useDeleteCompanies from "../../../../hooks/companies/useDeleteCompanies";
import Loader from "../../../Loader/Loader";
import { Trans, useTranslation } from "react-i18next";

export default function DeleteModal({
  selected,
  setShowModal,
  setSelected,
}: {
  selected: number[];
  setShowModal: Dispatch<SetStateAction<boolean>>;
  setSelected: Dispatch<SetStateAction<number[]>>;
}) {
  const { t } = useTranslation();
  const {
    mutateDeleteCompanies,
    isPendingDeleteCompanies,
    isErrorDeleteCompanies,
    isSuccessDeleteCompanies,
    message,
  } = useDeleteCompanies(setShowModal, setSelected);

  const count = selected.length

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-blue-dark rounded-xl shadow-lg p-6 w-[90%] max-w-md text-center">
        <h3 className="text-xl font-semibold text-yellow-300">
          {t("confirmDeletion")}
        </h3>
        <p className="text-yellow-300 mt-2">
          <Trans i18nKey="deleteConfirmation" count={count}>
            Are you sure you want to delete
            <span className="font-semibold">{count}</span> company?
          </Trans>
        </p>

        <div className="flex justify-center gap-4 mt-6">
          <button
            onClick={() => mutateDeleteCompanies({ ids: selected })}
            className="cursor-pointer bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-md font-semibold transition"
          >
            {t("delete")}
          </button>
          <button
            onClick={() => setShowModal(false)}
            className="cursor-pointer bg-gray-200 hover:bg-gray-300 text-gray-800 px-4 py-2 rounded-md font-semibold transition"
          >
            {t("cancel")}
          </button>
        </div>
        {isPendingDeleteCompanies && <Loader />}
        {isSuccessDeleteCompanies && (
          <p className="text-green-600 font-semibold">{message}</p>
        )}
        {isErrorDeleteCompanies && (
          <p className="text-red-600 font-semibold">{message}</p>
        )}
      </div>
    </div>
  );
}
