import { useMutation, useQueryClient } from "@tanstack/react-query";
import customRequest from "../../lib/axios";
import { useState } from "react";
import type { SetJobStatusPayload } from "../../types/jobs";

export default function useSetStatus() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");

  const setJobStatus = async (data: SetJobStatusPayload) => {
    try {
      setMessage("");

      const response = await customRequest.post("/jobs/status-job", data);

      if (response.status !== 201) {
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
    mutate: mutateJobStatus,
    isPending: isPendingJobStatus,
    isSuccess: isSuccessJobStatus,
    isError: isErrorJobStatus,
  } = useMutation({
    mutationFn: setJobStatus,
    onSuccess: (data) => {
      console.log(`Job ${data.jobId} marked as ${data.status}`);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["jobs-applied-or-not-interested"] });
    },
    onError: (error) => {
      console.error("Failed to update job status:", error);
      setMessage(error.message);
    },
  });

  return {
    mutateJobStatus,
    isPendingJobStatus,
    isSuccessJobStatus,
    isErrorJobStatus,
    message,
  };
}
