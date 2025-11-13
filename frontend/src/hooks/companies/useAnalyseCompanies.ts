import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type Dispatch, type SetStateAction } from "react";
import customRequest from "../../lib/axios";

export interface AnalyseCompaniesPayload {
  ids: number[];
  type: "analyse" | "check";
}

export interface AnalyseCompaniesResponse {
  message: string;
  queued: number[];
}

export default function useAnalyseCompanies(
  setSelected: Dispatch<SetStateAction<number[]>>
) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const analyseCompanies = async (data: AnalyseCompaniesPayload) => {
    try {
      setMessage(null);

      const response = await customRequest.post<AnalyseCompaniesResponse>(
        "/companies/queue-companies",
        data
      );

      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err: any) {
      console.error("Error queuing analyse jobs:", err);

      if (err.response?.data?.message) {
        throw new Error(err.response.data.message);
      } else {
        throw new Error("An unexpected error occurred while queuing jobs.");
      }
    }
  };

  const {
    mutate: mutateAnalyseCompanies,
    isPending: isPendingAnalyseCompanies,
    isSuccess: isSuccessAnalyseCompanies,
    isError: isErrorAnalyseCompanies,
  } = useMutation({
    mutationFn: analyseCompanies,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      setMessage(data.message);
      setTimeout(() => setMessage(null), 3000);
      setSelected([]);
    },
    onError: (error) => {
      console.error("Error analysing companies:", error);
      setMessage(error.message);
    },
  });

  return {
    mutateAnalyseCompanies,
    isPendingAnalyseCompanies,
    isSuccessAnalyseCompanies,
    isErrorAnalyseCompanies,
    message,
  };
}
