import { useMutation, useQueryClient } from "@tanstack/react-query";
import customRequest from "../../lib/axios";
import { useState } from "react";

export interface UpdateCompanyPayload {
  id: number;
  name: string;
  website?: string;
  emails?: string[];
  internalJobListingPages?: string[];
  externalJobListingPages?: string[];
}

export default function useUpdateCompany() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const updateCompany = async (data: UpdateCompanyPayload) => {
    try {
      setMessage("");

      const response = await customRequest.put("/companies/company", data);

      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err: any) {
      if (err.response && err.response.data && err.response.data.message) {
        throw new Error(err.response.data.message);
      } else {
        throw new Error("An unexpected error occurred. Please try again.");
      }
    }
  };

  const {
    mutate: mutateCompany,
    isPending: isPendingMutateCompany,
    isSuccess: isSuccessMutateCompany,
    isError: isErrorMutateCompany,
  } = useMutation({
    mutationFn: updateCompany,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      setMessage(data.message);
      setTimeout(() => setMessage(null), 3000);
    },
    onError: (error) => {
      console.error("Error updating company:", error);
    },
  });

  return {
    mutateCompany,
    isPendingMutateCompany,
    isSuccessMutateCompany,
    isErrorMutateCompany,
    message,
  };
}
