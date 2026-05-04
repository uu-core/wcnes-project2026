#!/usr/bin/python3

# Hamming code decoder for analysis of received data
# This file was created using AI with our C-code implementation
# as input, then modified by us.

def is_power_of_two(n):
    """Check if n is a power of two (treating 0 as power of two per your C implementation)"""
    return ((n > 0) and ((n & (n-1)) == 0)) or n == 0

def build_buffer_mapping(encoded_bits, total_bits, data_bits):
    """
    Build the buffer mapping from encoded bits to logical positions.
    
    Args:
        encoded_bits: List of encoded bits
        total_bits: Total bits per Hamming block (e.g., 3, 7, 15)
        data_bits: Data bits per Hamming block (e.g., 1, 4, 11)
    
    Returns:
        tuple: (buffer, num_chunks, skip_interval)
    """
    skip_interval = total_bits + 1
    
    # Calculate number of chunks
    bits_per_chunk = total_bits  # Each chunk has total_bits (with 1 skip per chunk)
    num_chunks = len(encoded_bits) // total_bits
    
    # Build 1-indexed buffer with skip positions
    total_buffer_size = num_chunks * skip_interval
    buffer = [0] * (total_buffer_size + 1)
    
    encoded_idx = 0
    for pos in range(1, total_buffer_size + 1):
        if pos % skip_interval == 0:
            continue  # Skip position
        if encoded_idx < len(encoded_bits):
            buffer[pos] = encoded_bits[encoded_idx]
            encoded_idx += 1
    
    return buffer, num_chunks, skip_interval

def identify_parity_and_data_positions(total_bits, skip_interval):
    """
    Identify which positions within a chunk are parity vs data.
    
    Args:
        total_bits: Total bits per Hamming block
        skip_interval: Interval at which positions are skipped
    
    Returns:
        tuple: (parity_positions, data_positions)
    """
    parity_positions = []
    data_positions = []
    
    for pos in range(1, total_bits + 1):
        if is_power_of_two(pos % skip_interval):
            parity_positions.append(pos)
        else:
            data_positions.append(pos)
    
    return parity_positions, data_positions

def hamming_decode_chunk_flexible(encoded_bits, total_bits, data_bits):
    """
    Decode a single chunk with flexible Hamming configuration.
    
    Args:
        encoded_bits: List of bits for one chunk (total_bits length)
        total_bits: Total bits per Hamming block
        data_bits: Data bits per Hamming block
    
    Returns:
        tuple: (data_bits_extracted, syndrome, error_positions)
    """
    skip_interval = total_bits + 1
    
    # Build buffer for this chunk
    buffer = [0] * (skip_interval + 1)
    for i in range(total_bits):
        pos = i + 1
        if pos % skip_interval != 0:
            buffer[pos] = encoded_bits[i]
    
    # Identify parity and data positions
    parity_positions, data_positions = identify_parity_and_data_positions(total_bits, skip_interval)
    
    # Extract data bits
    extracted_data = []
    for pos in data_positions:
        if pos < len(buffer):
            extracted_data.append(buffer[pos])
    
    # Calculate syndrome
    syndrome = 0
    error_positions = []
    
    for parity_pos in parity_positions:
        if parity_pos >= len(buffer):
            continue
        
        stored_parity = buffer[parity_pos]
        
        # Recalculate parity (matches your C code logic)
        calculated_parity = 0
        check_start = parity_pos + 1
        check_end = parity_pos + total_bits
        
        for check_pos in range(check_start, check_end + 1):
            if check_pos % skip_interval == 0:
                continue
            if check_pos >= len(buffer):
                continue
            # Only check data bits (not other parity bits)
            if is_power_of_two(check_pos % skip_interval):
                continue
            
            if buffer[check_pos]:
                calculated_parity ^= 1
        
        if stored_parity != calculated_parity:
            syndrome |= parity_pos
            error_positions.append(parity_pos)
    
    return extracted_data, syndrome, error_positions

def hamming_decode_full_flexible(encoded_bits, total_bits, data_bits):
    """
    Decode full message with flexible Hamming configuration.
    
    Args:
        encoded_bits: Complete list of encoded bits
        total_bits: Total bits per Hamming block (e.g., 3, 7, 15)
        data_bits: Data bits per Hamming block (e.g., 1, 4, 11)
    
    Returns:
        tuple: (decoded_message, error_info)
    """
    if len(encoded_bits) % total_bits != 0:
        raise ValueError(f"Total bits ({len(encoded_bits)}) must be divisible by total_bits ({total_bits})")
    
    num_chunks = len(encoded_bits) // total_bits
    decoded_message = []
    error_info = []
    
    for chunk_idx in range(num_chunks):
        start = chunk_idx * total_bits
        chunk = encoded_bits[start:start + total_bits]
        
        data_bits_extracted, syndrome, error_positions = hamming_decode_chunk_flexible(
            chunk, total_bits, data_bits
        )
        
        decoded_message.extend(data_bits_extracted)
        
        if syndrome != 0:
            error_info.append({
                'chunk': chunk_idx,
                'syndrome': syndrome,
                'error_positions': error_positions,
                'chunk_bits': chunk
            })
    
    return decoded_message, error_info

def hamming_encode_flexible(data_bits, total_bits, data_bits_param):
    """
    Flexible encoder matching your C implementation.
    
    Args:
        data_bits: List of data bits to encode
        total_bits: Total bits per Hamming block
        data_bits_param: Data bits per Hamming block
    
    Returns:
        List of encoded bits
    """
    skip_interval = total_bits + 1
    num_chunks = len(data_bits)
    
    # Build buffer with skip positions
    total_buffer_size = num_chunks * skip_interval
    buffer = [0] * (total_buffer_size + 1)
    
    # Place data bits
    data_idx = 0
    for chunk_idx in range(num_chunks):
        base_pos = chunk_idx * skip_interval + 1
        for pos in range(1, total_bits + 1):
            if pos % skip_interval == 0:
                continue
            if not is_power_of_two(pos % skip_interval):
                # This is a data position
                if data_idx < len(data_bits):
                    buffer[base_pos + pos - 1] = data_bits[data_idx]
                    data_idx += 1
    
    # Calculate parity bits
    for chunk_idx in range(num_chunks):
        base_pos = chunk_idx * skip_interval + 1
        
        for parity_pos in range(1, total_bits + 1):
            if parity_pos % skip_interval == 0:
                continue
            if not is_power_of_two(parity_pos % skip_interval):
                continue  # Not a parity position
            
            actual_pos = base_pos + parity_pos - 1
            if actual_pos >= len(buffer):
                continue
            
            calculated_parity = 0
            check_start = actual_pos + 1
            check_end = actual_pos + total_bits
            
            for check_pos in range(check_start, check_end + 1):
                if check_pos % skip_interval == 0:
                    continue
                if check_pos >= len(buffer):
                    continue
                if is_power_of_two(check_pos % skip_interval):
                    continue  # Skip other parity bits
                
                if buffer[check_pos]:
                    calculated_parity ^= 1
            
            buffer[actual_pos] = calculated_parity
    
    # Extract encoded bits (excluding skip positions)
    encoded = []
    for pos in range(1, total_buffer_size + 1):
        if pos % skip_interval == 0:
            continue
        encoded.append(buffer[pos])
    
    return encoded

if __name__ == "__main__":
    # Verify against your C program output
    your_encoded_output = [0,1,1,0,0,1,1,0,0,1,1,0,0,1]
    decoded_your, errors_your = hamming_decode_full_flexible(your_encoded_output, 7, 4)
    
    print(f"Your encoded output: {''.join(map(str, your_encoded_output))}")
    print(f"Decoded:             {''.join(map(str, decoded_your))}")
    # TODO: use ground truth data from payload_for_peudo_seq() 
    print(f"Expected:            10111001")
    print(f"Errors: {''.join(map(str, errors_your))}")
    print(f"Match:               {'✓ PASS' if ''.join(map(str, decoded_your)) == '10111001' else '✗ FAIL'}")