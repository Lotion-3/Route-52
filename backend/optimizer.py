from itertools import combinations, permutations
from typing import List, Dict, Tuple, Union, Optional, Set, Any
import re
import config

# --- CORE OPTIMIZATION FUNCTIONS ---
def calculate_split_shopping_price(
    shopping_list: List[Dict[str, Union[str, int]]],
    store_ids: List[str], 
    price_database: Dict[str, Dict[str, float]],
    max_cost_threshold: float = float('inf')
) -> Tuple[float, Dict[str, int]]:
    """
    Calculates the minimum total cost, considering item quantities, and returns 
    the total quantity of units assigned to each store.
    """
    total_price = 0.0
    item_assignment_counts: Dict[str, int] = {s: 0 for s in store_ids} 
    
    for item_data in shopping_list: 
        item = item_data["name"].lower().strip()
        quantity = item_data["qty"]
        
        min_item_cost = float('inf') 
        best_store = None
        
        # Find the cheapest price for this item among the selected stores
        for store_id in store_ids:
            s_id = store_id.strip() # Standardize inside lookup
            unit_price = price_database.get(s_id, {}).get(item, float('inf'))
            if unit_price != float('inf'):
                cost = unit_price * quantity
                if cost < min_item_cost:
                    min_item_cost = cost
                    best_store = store_id 
        
        if min_item_cost == float('inf'):
            return float('inf'), item_assignment_counts 
            
        total_price += min_item_cost
        
        # Optimization: Early exit if we already exceed the best known price
        if total_price >= max_cost_threshold:
            return float('inf'), item_assignment_counts

        if best_store:
            item_assignment_counts[best_store] += int(quantity)
            
    return total_price, item_assignment_counts

def find_fastest_travel_permutation(
    store_indices_subset: Tuple[int, ...], 
    durations_matrix: List[List[float]], 
    start_index: int
) -> Tuple[Tuple[int, ...], float]:
    """
    For a given set of stores (subset), find the fastest order (permutation) to visit them.
    Returns: (best_route_indices, min_travel_time)
    """
    min_travel_time = float('inf')
    best_route_indices = store_indices_subset
    
    for route_indices in permutations(store_indices_subset):
        travel_time = 0.0
        current_index = start_index
        
        # Sum travel time: Start -> S1 -> S2 -> ...
        for next_index in route_indices:
            travel_time += durations_matrix[current_index][next_index]
            current_index = next_index
            
        # Add return trip: ... -> Sk -> Start
        travel_time += durations_matrix[current_index][start_index]
        
        if travel_time < min_travel_time:
            min_travel_time = travel_time
            best_route_indices = route_indices
            
    return best_route_indices, min_travel_time

def find_optimal_store(
    durations_matrix: List[List[float]],
    price_database: Dict[str, Dict[str, float]],
    location_names: List[str],
    shopping_list: List[Dict[str, Union[str, int]]]
) -> Tuple[List[str], float, float, Dict[str, List[Dict[str, Any]]], float, str]:
    """
    Finds the route (1 to N stores) with the lowest combined shopping price 
    that meets the total time constraint.
    """
    start_index = location_names.index("Start")
    optimal_route: List[str] = []
    min_cost = float('inf')
    best_total_time = 0.0
    
    # Check if there are any items to shop for
    if not shopping_list:
        print("No items to shop for. Cannot run optimization.")
        return [], 0.0, 0.0, {}, 0.0, ""
    
    print(f"\n=== OPTIMIZER: CRUNCHING PRE-FETCHED PRICES ===")
    print(f"Items to buy: {len(shopping_list)}")
    print(f"Time limit: {int(config.MAX_TIME_SECONDS / 60)} minutes.")
    
    store_indices = list(range(1, len(location_names)))
    
    # Set to store subsets (as frozensets of indices) that failed the time constraint 
    failed_time_subsets: Set[frozenset[int]] = set()
    
    k1_winner_store_id: Union[str, None] = None

    # --- Phase 1: Calculate Baseline (k=1) Costs and Find Best Single Stop ---
    print("\nPhase 1: Calculating Baseline (k=1) Costs ---")
    k = 1 
    cheapest_single_store_cost = float('inf')
    cheapest_single_store_name = ""
    
    for store_indices_subset in combinations(store_indices, k):
        current_store_index = store_indices_subset[0]
        route_store_ids = [location_names[current_store_index]]
        store_id = route_store_ids[0].strip() # Standardize stripping

        # 1. Calculate Optimal Item Assignment and Cost
        item_cost, item_quantity_counts = calculate_split_shopping_price(
            shopping_list, 
            route_store_ids, 
            price_database
        )
        
        if item_cost == float('inf'):
            continue
            
        # --- CALCULATE SHOPPING TIME ---
        store_type = store_id.split(' ')[0] 
        multiplier = config.STORE_TIME_MULTIPLIERS.get(store_type, 1.0)
        quantity_s = item_quantity_counts.get(store_id, 0)
        total_shopping_time_seconds = (config.BASE_FIXOUT_OVERHEAD * multiplier) + (quantity_s * config.TIME_PER_UNIT_SECONDS)

        # 2. Find Fastest Travel Permutation 
        store_index = location_names.index(store_id)
        min_travel_time = durations_matrix[start_index][store_index] + durations_matrix[store_index][start_index]
        
        # 3. Calculate Full Time 
        total_time_seconds = min_travel_time + total_shopping_time_seconds

        # --- BENCHMARK CALCULATION (Independent of Time) ---
        if item_cost < cheapest_single_store_cost:
            cheapest_single_store_cost = item_cost
            cheapest_single_store_name = store_id

        # 4. Update Optimal
        if total_time_seconds <= config.MAX_TIME_SECONDS:
            if item_cost < min_cost:
                min_cost = item_cost 
                optimal_route = route_store_ids
                best_total_time = total_time_seconds
                k1_winner_store_id = store_id
                print(f" -> Best single store: {store_id} at ${item_cost:.2f}")
        else:
            pass # print(f"Route [1 Stop: {store_id}]: ❌ Time Exceeded")

    # --- Phase 2: Store Filtering (Item-Based Pruning) ---
    if min_cost == float('inf') or k1_winner_store_id is None:
        print("\nPruning: No single-stop route was time-feasible.")
        # We continue to k=2 because maybe split stores are closer? 
        # Actually usually if 1 stop is too far, 2 stops are worse, but not always if split across different directions.
        eligible_multistop_indices = store_indices
    else:
        eligible_multistop_indices: List[int] = []
        print(f"\nPhase 2: Store Pruning (Based on Item Price vs Winner: {k1_winner_store_id}) ---")
        
        for index in store_indices:
            store_id = location_names[index]
            if store_id == k1_winner_store_id:
                eligible_multistop_indices.append(index)
                continue
                
            is_store_useful = False
            for item_data in shopping_list:
                item_name = item_data["name"].lower().strip()
                winner_unit_price = price_database.get(k1_winner_store_id, {}).get(item_name, float('inf'))
                store_unit_price = price_database.get(store_id, {}).get(item_name, float('inf'))
                if store_unit_price < winner_unit_price:
                    is_store_useful = True
                    break
            
            if is_store_useful:
                eligible_multistop_indices.append(index)

    # --- Phase 3: Run k=2 to max_k using only eligible_multistop_indices ---
    print(f"\nPhase 3: Running k>1 Optimization on {len(eligible_multistop_indices)} Eligible Stores ---")
    
    max_k_eligible = min(len(eligible_multistop_indices), 3) # Cap at 3 for performance
    
    for k in range(2, max_k_eligible + 1):
        found_any_time_feasible_subset_at_k = False 
        for store_indices_subset in combinations(eligible_multistop_indices, k):
            # --- SUBSET PRUNING CHECK (Time Pruning) ---
            current_set = frozenset(store_indices_subset)
            is_superset_of_failed = any(failed_set.issubset(current_set) for failed_set in failed_time_subsets)
            if is_superset_of_failed:
                continue

            route_store_ids = [location_names[i] for i in store_indices_subset]
            
            # --- 1. Calculate Optimal Item Assignment and Cost ---
            item_cost, item_quantity_counts = calculate_split_shopping_price(
                shopping_list, 
                route_store_ids, 
                price_database,
                max_cost_threshold=min_cost
            )
            
            if item_cost == float('inf'):
                continue
            
            # --- CALCULATE SHOPPING TIME ---
            total_shopping_time_seconds = 0.0
            min_one_way_travel = float('inf')

            for store_id in route_store_ids:
                store_type = store_id.split(' ')[0] 
                multiplier = config.STORE_TIME_MULTIPLIERS.get(store_type, 1.0)
                quantity_s = item_quantity_counts.get(store_id, 0)
                store_time = (config.BASE_FIXOUT_OVERHEAD * multiplier) + (quantity_s * config.TIME_PER_UNIT_SECONDS)
                total_shopping_time_seconds += store_time
                
                store_index = location_names.index(store_id)
                travel_to_store = durations_matrix[start_index][store_index]
                if travel_to_store < min_one_way_travel:
                    min_one_way_travel = travel_to_store

            # --- EFFICIENCY: AGGRESSIVE TIME PRUNING ---
            lower_bound_total_time = (2 * min_one_way_travel) + total_shopping_time_seconds
            if lower_bound_total_time > config.MAX_TIME_SECONDS:
                 continue
            
            found_any_time_feasible_subset_at_k = True 

            # --- 2. Find Fastest Travel Permutation ---
            best_route_indices, min_travel_time = find_fastest_travel_permutation(
                store_indices_subset, durations_matrix, start_index
            )
            
            # --- 3. Calculate Full Time ---
            total_time_seconds = min_travel_time + total_shopping_time_seconds
            
            if total_time_seconds > config.MAX_TIME_SECONDS:
                failed_time_subsets.add(current_set) 
                continue 
            
            # --- 4. Update Optimal ---
            if item_cost < min_cost:
                min_cost = item_cost
                optimal_route = [location_names[i] for i in best_route_indices]
                best_total_time = total_time_seconds
                print(f" -> Found better {k}-store route: {optimal_route} at ${item_cost:.2f}")
            
        if not found_any_time_feasible_subset_at_k and optimal_route:
            break

    # Re-calculate assignments for the final winner
    _, final_assignment_counts = calculate_split_shopping_price(shopping_list, optimal_route, price_database)
    
    # Format assignments for return (List[str] per store)
    final_assignments = {s: [] for s in optimal_route}
    for item_data in shopping_list:
        item = item_data["name"]
        quantity = item_data["qty"]
        best_price = float('inf')
        best_s = None
        for s in optimal_route:
            p = price_database.get(s, {}).get(item.lower().strip(), float('inf'))
            if p < best_price:
                best_price = p
                best_s = s
        if best_s:
            final_assignments[best_s].append({"name": item, "qty": quantity})

    print(f"DEBUG OPTIMIZER: Found cheapest single store as {cheapest_single_store_name} for ${cheapest_single_store_cost:.2f}", flush=True)
    return optimal_route, min_cost, best_total_time, final_assignments, cheapest_single_store_cost, cheapest_single_store_name
