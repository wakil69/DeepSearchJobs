import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type Dispatch, type SetStateAction } from "react";
import customRequest from "../../lib/axios";

export interface DeleteCompaniesPayload {
  ids: number[];
}

export default function useDeleteCompanies(
  setShowModal: Dispatch<SetStateAction<boolean>>,
  setSelected: Dispatch<SetStateAction<number[]>>
) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const deleteCompanies = async (data: DeleteCompaniesPayload) => {
    try {
      setMessage(null);

      const response = await customRequest.delete("/companies/", {
        data,
        headers: {
          "Content-Type": "application/json",
        },
      });
      
      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err: any) {
      console.error("Error deleting companies:", err);
      if (err.response?.data?.message) {
        throw new Error(err.response.data.message);
      } else {
        throw new Error("An unexpected error occurred. Please try again.");
      }
    }
  };

  const {
    mutate: mutateDeleteCompanies,
    isPending: isPendingDeleteCompanies,
    isSuccess: isSuccessDeleteCompanies,
    isError: isErrorDeleteCompanies,
    error,
  } = useMutation({
    mutationFn: deleteCompanies,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["all-companies"] });
      setMessage(data.message);
      setTimeout(() => {
        setMessage(null);
      }, 3000);
      setShowModal(false);
      setSelected([])
    },
    onError: (error) => {
      console.error("Error deleting companies:", error);
    },
  });

  return {
    mutateDeleteCompanies,
    isPendingDeleteCompanies,
    isSuccessDeleteCompanies,
    isErrorDeleteCompanies,
    message,
    error,
  };
}
