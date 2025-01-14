import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_optimized_worker_count():
    """Determine the optimal number of workers (75% of cores or 1)."""
    total_cores = multiprocessing.cpu_count()
    return max(1, int(0.75 * total_cores))

def parallel_task_execution(task_function, task_list, *args):
    """
    Execute tasks in parallel using ThreadPoolExecutor.
    Args:
        task_function: The function to execute in parallel.
        task_list: A list of tasks to process.
        *args: Additional arguments for the task function.
    Returns:
        List of results from completed tasks.
    """
    worker_count = get_optimized_worker_count()
    results = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_task = {
            executor.submit(task_function, task, *args): task for task in task_list
        }

        for future in as_completed(future_to_task):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"Task {future_to_task[future]} encountered an error: {e}")

    return results
