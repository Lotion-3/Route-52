from itertools import combinations
from typing import List, Dict, Tuple, Union, Optional
import re
import config

# --- CORE OPTIMIZATION FUNCTIONS ---
def calculate_split_shopping_price(
    shopping_list: List[Dict[str, Union[str, int]]],
    store_ids: List[str], 
    price_database: Dict[str, Dict[str, float]],
    max_cost_threshold: float = float('inf')
) -> Tuple[float, Dict[str, List[str]]]:
    
    total_price = 0.0
    item_assignments = {s: [] for s in store_ids}
    
    for item_data in shopping_list:
        item_name = item_data["name"]
        quantity = item_data["qty"]
        min_item_cost = float('inf')
        best_store = None
        
        for store_id in store_ids:
            store_inventory = price_database.get(store_id, {})
            # Direct lookup since keys are guaranteed to match by price_manager
            unit_price = store_inventory.get(item_name)
            
            if unit_price is not None:
                cost = unit_price * quantity
                if cost < min_item_cost:
                    min_item_cost = cost
                    best_store = store_id
        
        if min_item_cost == float('inf'):
            # Item not found in ANY of the stores
            return float('inf'), item_assignments
        
        total_price += min_item_cost
        
        # Optimization: Early exit if we already exceed the best known price
        if total_price > max_cost_threshold:
            return float('inf'), item_assignments
            
        if best_store:
            item_assignments[best_store].append(f"{item_name} (x{quantity})")
            
    return total_price, item_assignments

def find_optimal_store(
    durations_matrix: List[List[float]],
    price_database: Dict[str, Dict[str, float]],
    location_names: List[str],
    shopping_list: List[Dict[str, Union[str, int]]]
) -> Tuple[List[str], float, float, Dict[str, List[str]]]:
    
    start_index = location_names.index("Start")
    optimal_route = []
    min_cost = float('inf')
    best_total_time = 0.0
    optimal_assignments = {}
    
    # Map store name to its matrix index
    name_to_idx = {name: i for i, name in enumerate(location_names)}
    store_names_only = [n for n in location_names if n != "Start"]

    print("\n=== OPTIMIZER: CRUNCHING PRE-FETCHED PRICES ===")
    print(f"Items to buy: {len(shopping_list)}")
    
    # -----------------------------------------------------
    # PHASE 1: SINGLE STORE BASELINE
    # -----------------------------------------------------
    print("Phase 1: Finding best single store...")
    
    valid_single_stores = []
    
    for store_id in store_names_only:
        cost, assignments = calculate_split_shopping_price(shopping_list, [store_id], price_database)
        
        if cost == float('inf'):
            continue  # Store doesn't have everything
            
        store_idx = name_to_idx[store_id]
        travel_time = durations_matrix[start_index][store_idx] + durations_matrix[store_idx][start_index]
        shopping_time = config.BASE_FIXOUT_OVERHEAD + (len(shopping_list) * config.TIME_PER_UNIT_SECONDS)
        total_time = travel_time + shopping_time
        
        if total_time <= config.MAX_TIME_SECONDS:
            valid_single_stores.append((store_id, cost))
            if cost < min_cost:
                min_cost = cost
                optimal_route = [store_id]
                best_total_time = total_time
                optimal_assignments = assignments

    if optimal_route:
        print(f" -> Current Best: {optimal_route} at ${min_cost:.2f}")
    else:
        print(" -> No single store has all items within time limit.")

    # -----------------------------------------------------
    # PHASE 2: PRUNING
    # -----------------------------------------------------
    eligible_for_combo = []
    
    if min_cost != float('inf'):
        eligible_for_combo = store_names_only 
    else:
        eligible_for_combo = store_names_only

    # -----------------------------------------------------
    # PHASE 3: MULTI-STORE COMBINATIONS (Pairs)
    # -----------------------------------------------------
    print("Phase 2: Checking 2-store combinations...")
    
    # Generate all pairs
    combos = list(combinations(eligible_for_combo, 2))
    
    for store_a, store_b in combos:
        idx_a = name_to_idx[store_a]
        idx_b = name_to_idx[store_b]
        
        # 1. Travel Time Check (Start -> A -> B -> Start)
        t_start_a = durations_matrix[start_index][idx_a]
        t_a_b     = durations_matrix[idx_a][idx_b]
        t_b_start = durations_matrix[idx_b][start_index]
        route_1_time = t_start_a + t_a_b + t_b_start
        
        t_start_b = durations_matrix[start_index][idx_b]
        t_b_a     = durations_matrix[idx_b][idx_a]
        t_a_start = durations_matrix[idx_a][start_index]
        route_2_time = t_start_b + t_b_a + t_a_start
        
        # Use the faster driving route
        travel_time = min(route_1_time, route_2_time)
        
        # Add Shopping Time
        shopping_time = (config.BASE_FIXOUT_OVERHEAD * 2) + (len(shopping_list) * config.TIME_PER_UNIT_SECONDS)
        
        total_time = travel_time + shopping_time
        
        if total_time > config.MAX_TIME_SECONDS:
            continue # Skip this pair, too far
            
        # 2. Cost Check (With Early Exit)
        cost, assignments = calculate_split_shopping_price(
            shopping_list, 
            [store_a, store_b], 
            price_database, 
            max_cost_threshold=min_cost
        )
        
        if cost < min_cost:
            min_cost = cost
            # Determine order for display based on travel time
            if route_1_time < route_2_time:
                optimal_route = [store_a, store_b]
            else:
                optimal_route = [store_b, store_a]
            best_total_time = total_time
            optimal_assignments = assignments
            print(f" -> Found better combo: {optimal_route} at ${min_cost:.2f}")

    return optimal_route, min_cost, best_total_time, optimal_assignments