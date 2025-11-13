import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import customRequest from "../../lib/axios";

export interface ImportCompaniesResponse {
  message: string;
  importedCount: number;
}

export default function useImportCompanies() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  /**
   * Upload a CSV or XLSX file to import companies
   */
  const importCompanies = async (
    file: File
  ): Promise<ImportCompaniesResponse> => {
    if (!file) throw new Error("No file selected");

    const formData = new FormData();
    formData.append("file", file);

    const response = await customRequest.post<ImportCompaniesResponse>(
      "/companies/",
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      }
    );

    return response.data;
  };

  const {
    mutate: mutateImportCompanies,
    isPending: isPendingImportCompanies,
    isSuccess: isSuccessImportCompanies,
    isError: isErrorImportCompanies,
  } = useMutation({
    mutationFn: importCompanies,
    onSuccess: (data) => {
      setMessage(data.message);
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["all-companies"] });
      setTimeout(() => setMessage(null), 3000);
    },
    onError: (error: any) => {
      console.error("Error importing companies:", error);
      setMessage(
        error?.response?.data?.message ??
          "An error occurred while importing companies."
      );
    },
  });

  return {
    mutateImportCompanies,
    isPendingImportCompanies,
    isSuccessImportCompanies,
    isErrorImportCompanies,
    message,
  };
}
