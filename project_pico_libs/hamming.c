#include <math.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include "hamming.h"


uint8_t is_power_of_two(uint16_t n) {
    // Adapted from https://www.geeksforgeeks.org/dsa/program-to-find-whether-a-given-number-is-power-of-2/
    // Check if n is positive and n & (n-1) is 0
    // Considers 0 a power of two 😎
    return ((n > 0) && ((n & (n-1)) == 0)) || n == 0;
}

void fill_zeroes(uint8_t *arr, uint16_t length)
{
    for(int i = 0; i < length; i++)
    {
        arr[i] = 0;
    }
}

/**
 * Packs an array of single-bit values (0 or 1) into a compact byte array.
 * Helper method created by AI (lumo.proton.me), adapted to fit our use case
 * @param src Pointer to the source array of bits (each element is 0 or 1).
 * @param src_len Number of bits in the source array.
 * @param dest Pointer to the destination array (must be at least ceil(src_len / 8) bytes).
 */
void pack_bits_to_bytes(const uint8_t *src, size_t src_len, uint8_t *dest) {
    if (src == NULL || dest == NULL || src_len == 0) {
        return 0;
    }

    size_t dest_len = (src_len + 7) / 8; // Ceiling division
    size_t byte_idx = 0;
    uint8_t current_byte = 0;
    uint8_t bit_count = 0;

    for (size_t i = 0; i < src_len; ++i) {
        // Shift the current bit into position (MSB first: bit 7 down to 0)
        // If src[i] is 1, set the bit; if 0, leave it as 0.
        if (src[i] & 1) {
            current_byte |= (1 << (7 - bit_count));
        }

        bit_count++;

        // If we have collected 8 bits, write the byte and reset
        if (bit_count == 8) {
            dest[byte_idx++] = current_byte;
            current_byte = 0;
            bit_count = 0;
        }
    }

    // Handle any remaining bits (less than 8 at the end)
    if (bit_count > 0) {
        dest[byte_idx++] = current_byte;
    }
}

void encode(uint8_t *byte_array, uint16_t payload_length_bits, uint8_t total_bits, uint8_t data_bits, uint8_t *buffer)
{
    //             total bits after =           data bits + parity bits
    uint16_t total_bits_with_parity = payload_length_bits + ceil((double)payload_length_bits/data_bits) * (total_bits - data_bits);
    total_bits_with_parity += payload_length_bits / data_bits; // Add extra bits for easier processing

    /*
    Move data bits to output buffer
    Our format is 
    Input: 1111 1111              (8 data bits)
    Output: X001 0111 X001 0111   (14 "useful" bits, 16 bits total)
    where X is unused (index 0 is not a good parity bit index)
    */ 
    uint8_t payload_index = 0;
    for (uint16_t bit_index = 1; bit_index < total_bits_with_parity; bit_index++) 
    {
        if (bit_index % (total_bits + 1) == 0)
            continue;
        if(!is_power_of_two(bit_index % (total_bits + 1)))
        {
            // This is a data bit, just copy it
            buffer[bit_index] = byte_array[payload_index];
            payload_index++;
        }
    }

    // Calculate parity
    for (uint16_t bit_index = 1; bit_index < total_bits_with_parity; bit_index++) {
        if(bit_index % (total_bits + 1) == 0)
            continue;
        if (is_power_of_two(bit_index % (total_bits + 1)))
        {
            // printf("At %d we found a power of two, so this should be a parity bit\n", bit_index);
            uint8_t parity = 0;
            // This is a parity bit, do maths
            // Xpp1p011 Xpp1p011
            //  ^<---->  Check these bits for the selected parity bit        
            for(uint16_t chunk_bit = bit_index + 1; chunk_bit < bit_index + total_bits; chunk_bit++)
            {
                // printf("Parity bit %d checking chunk bit %d\n", bit_index, chunk_bit);
                /* 
                Check all data bits which index has the bit of the parity bit set, e.g.:
                Xpp1p011 
                 ^ ^ ^ ^ => Parity is the number of 1's in these data bits (even or odd)
                _1_3_5_7 bit pos, "_" is don't care
                */
                // printf("DEBUG: %d mod %d and %d equals %d\n", bit_index, (total_bits + 1), chunk_bit, (bit_index % (total_bits + 1)) & chunk_bit);
                if ((bit_index % (total_bits + 1)) & chunk_bit) // Check that data bit position matches parity bit (e.g. bit 2 set in data bit pos for p2)
                {
                    // printf("Parity bit %b matches chunk bit %b\n", bit_index, chunk_bit);
                    // printf("DEBUG: %d mod %d equals %d\n", chunk_bit, total_bits+1, (chunk_bit % total_bits + 1));
                    if (!is_power_of_two(chunk_bit % (total_bits + 1))) // Only check data bits
                    {
                        // printf("Parity bit %d will contain bit %d\n", bit_index, chunk_bit);
                        // printf("Value of bit to be checked is %b\n", buffer[chunk_bit]);
                        if (buffer[chunk_bit]) // Only count 1's
                        {
                            parity = (parity + 1) % 2; // Even or odd num of 1's
                        }
                        // printf("parity bit %d has value %d\n", bit_index, parity);
                            
                    }
                    // else
                    // {
                    //     printf("Bit index %d: Chunk bit %d is a parity bit\n", bit_index, chunk_bit);
                    // }
                }
            }
            if (parity)
            {
                // printf("Setting parity bit %d to 1\n", bit_index);
                buffer[bit_index] = 1;
            }
        }
    }
}

int main()
{
    /*
    Example
    Input: 1011 1011
    Result should be: 0110011 0110011
    uint8_t arr[] = {0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1};
    */

    // uint8_t arr[] = {0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1,0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x1, 0x1};
    uint8_t arr[] = {0x1, 0x0, 0x1, 0x1, 0x1, 0x0, 0x0, 0x1};
    uint16_t arr_size = sizeof(arr) / sizeof(arr[0]);
    printf("Arr size: %d\n", arr_size);
    uint16_t total_bits_with_parity = arr_size + ceil((double)arr_size/DATA_BITS) * (TOTAL_BITS - DATA_BITS);
    total_bits_with_parity += arr_size / DATA_BITS;
    uint8_t output[total_bits_with_parity];
    fill_zeroes(output, total_bits_with_parity);

    encode(arr, sizeof(arr) / sizeof(arr[0]), TOTAL_BITS, DATA_BITS, output);

    printf("Here is the result\n");
    for (int i = 1; i <= total_bits_with_parity; i++) 
    {
        if(i % (TOTAL_BITS + 1) == 0)
        {
            //printf("X ");
            continue;
        }
            
        printf("%b", output[i]);   
    }

    printf("\n");

    return 0;
}


