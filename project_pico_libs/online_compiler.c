/******************************************************************************

                            Online C Compiler.
                Code, Compile, Run and Debug C program online.
Write your code in this editor and press "Run" button to compile and execute it.

*******************************************************************************/
#include <math.h>

#include <stdint.h>
#include <inttypes.h>

//byte_array = [0011 1100, 
//                1101 0011]
//byte_array = [0011 1100, 1101 0011]

// Payload = 14B -> 112bits 
// Closest: Hamming(127, 120) 7 parity
// 112/4*3  Hamming(7, 4)     84 parity

/* Set a bit (0-7) */
#define SET_BIT(byte, bit_pos)   ((byte) | (1U << (bit_pos)))

/* Clear a bit (0-7) */
#define CLEAR_BIT(byte, bit_pos) ((byte) & ~(1U << (bit_pos)))

/* Toggle a bit (0-7) */
#define TOGGLE_BIT(byte, bit_pos) ((byte) ^ (1U << (bit_pos)))

/* Check if a bit is set (returns non-zero or 0) */
#define CHECK_BIT(byte, bit_pos) (((byte) >> (bit_pos)) & 1U)

/* Check if a bit is set (returns true/false) */
#define IS_BIT_SET(byte, bit_pos) ((((byte) >> (bit_pos)) & 1U) != 0)
#include <stdio.h>

// Hamming 7,4
#define TOTAL_BITS 7
#define DATA_BITS 4


uint8_t is_power_of_two(uint16_t n) {
    // from https://www.geeksforgeeks.org/dsa/program-to-find-whether-a-given-number-is-power-of-2/
    // Check if n is positive and n & (n-1) is 0
    return ((n > 0) && ((n & (n-1)) == 0)) || n == 0;
}

void fill_zeroes(uint8_t *arr, uint16_t length)
{
    for(int i = 0; i < length; i++)
    {
        arr[i] = 0;
    }
}

void encode(uint8_t *byte_array, uint16_t payload_length_bits, uint8_t total_bits, uint8_t data_bits, uint8_t *buffer)
{
    //             total bits after =           data bits + parity bits
    uint16_t total_bits_with_parity = payload_length_bits + ceil((double)payload_length_bits/data_bits) * (total_bits - data_bits);
    total_bits_with_parity += payload_length_bits / data_bits;
    // uint8_t output_buffer_bytes = (uint8_t)ceil((double)total_bits_with_parity/8);
    uint8_t output_buffer[total_bits_with_parity];

    fill_zeroes(output_buffer, total_bits_with_parity);
    

    
    //uint8_t *ptr = output_buffer;

    // 0 -> p1: i % total_bits == 0
    // 1 -> p2: i % total_bits == 1
    // 2 -> d1
    // 3 -> p4: i % total_bits == 3
    // 4 -> d2
    // 5 -> d3
    // 6 -> d4

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
            // printf("%d is not a power of 2\n", bit_index % (total_bits + 1));
            // printf("%d is not a power of two. Counter at index %d\n", bit_index, counter);
            // This is a data bit, just copy it
            // output_buffer[output_bit_index] = byte_array[counter] & bit_index % 8;
            // printf("Idx %d gets value %d (idx %d)\n", bit_index, byte_array[payload_index], payload_index);
            output_buffer[bit_index] = byte_array[payload_index];
            payload_index++;
        }
        // else
        //     printf("%d is a power of 2\n", bit_index % (total_bits + 1));
        printf("Bit: %b\n", output_buffer[bit_index]);
        
    }

    // Calculate parity
    // Xpp1p011 Xpp1p011
    //  ^              ^
    for (uint16_t bit_index = 1; bit_index < total_bits_with_parity; bit_index++) {
        if(bit_index % (total_bits + 1) == 0)
            continue;
        if (is_power_of_two(bit_index % (total_bits + 1)))
        {
            printf("At %d we found a power of two, so this should be a parity bit\n", bit_index);
            uint8_t parity = 0;
            // This is a parity bit, do maths
            // Xpp1p011 Xpp1p011
            //  ^     ^         
            for(uint16_t chunk_bit = bit_index + 1; chunk_bit < bit_index + total_bits; chunk_bit++)
            {
                printf("Parity bit %d checking chunk bit %d\n", bit_index, chunk_bit);
                // Loopa över alla databitar, parity beräknas på de databitar där 0bPARITY_IDX & 0bDATA_IDX != 0
                // Xpp1p011 
                //  ^ ^ ^ ^ => Num of 1's in these data bits (even or odd)
                // _1_3_5_7
                // Xpp1p011 
                //   ^   ^^ => Num of 1's in these data bits (even or odd)
                // __2___67
                // Xpp1p011 
                //     ^ ^^ => Num of 1's in these data bits (even or odd)
                // ____4_67
                printf("DEBUG: %d mod %d and %d equals %d\n", bit_index, (total_bits + 1), chunk_bit, (bit_index % (total_bits + 1)) & chunk_bit);
                if ((bit_index % (total_bits + 1)) & chunk_bit) // Check that data bit position matches parity bit (e.g. bit 2 set in data bit pos for p2)
                {
                    printf("Parity bit %b matches chunk bit %b\n", bit_index, chunk_bit);
                    printf("DEBUG: %d mod %d equals %d\n", chunk_bit, total_bits+1, (chunk_bit % total_bits + 1));
                    if (!is_power_of_two(chunk_bit % (total_bits + 1))) // Only check data bits
                    {
                        printf("Parity bit %d will contain bit %d\n", bit_index, chunk_bit);
                        printf("Value of bit to be checked is %b\n", output_buffer[chunk_bit]);
                        if (output_buffer[chunk_bit]) // Only count 1's
                        {
                            
                            parity = (parity + 1) % 2; // Even or odd num of 1's
                            
                        }
                        printf("parity bit %d has value %d\n", bit_index, parity);
                            
                    }
                    else
                    {
                        printf("Bit index %d: Chunk bit %d is a parity bit\n", bit_index, chunk_bit);
                    }
                }
            // Om j % 
            }
            if (parity)
            {
                printf("Setting parity bit %d to 1\n", bit_index);
                //SET_BIT(output_buffer[output_bit_index], bit_index % 8);
                output_buffer[bit_index] = 1;
            }
            else
            {
                printf("Setting parity bit %d to 0\n", bit_index);
                //CLEAR_BIT(output_buffer[output_bit_index], bit_index % 8);
                output_buffer[bit_index] = 0;
            }
        }

    }
    for (int i = 0; i < total_bits_with_parity; i++)
        buffer[i] = output_buffer[i];
//    return 0;
}

int main()
{
    printf("Hello World\n");
    // uint8_t arr[] = {(uint8_t) 0x1, (uint8_t) 0x1, (uint8_t) 0x1, (uint8_t) 0x1, (uint8_t) 0x1, (uint8_t) 0x0, (uint8_t) 0x1, (uint8_t) 0x1};
    // uint8_t arr[] = {(uint8_t) 0x0, (uint8_t) 0x0, (uint8_t) 0x0, (uint8_t) 0x1, (uint8_t) 0x0, (uint8_t) 0x0, (uint8_t) 0x0, (uint8_t) 0x1};
    uint8_t arr[] = {(uint8_t) 0x1, (uint8_t) 0x1, (uint8_t) 0x0, (uint8_t) 0x0, (uint8_t) 0x1, (uint8_t) 0x0, (uint8_t) 0x1, (uint8_t) 0x1};
    /*
    
       Input: 1011 1011
       Result should be: 0110011 0110011

    */

         /*
-    Example: 1 Byte Input
-
-    Input: 11001011 (8 bits)
-
-    Split into two 4-bit groups:
-
-        Group 1: 1100 → 0111100
-        Group 2: 1011 → 0110011
 
-    Output: 0111100 0110011 (14 bits)
     */
    
    uint16_t total_bits_with_parity = 8 + ceil((double)8/DATA_BITS) * (TOTAL_BITS - DATA_BITS);
    total_bits_with_parity += (TOTAL_BITS + 1) / DATA_BITS;
    uint8_t output[total_bits_with_parity];
    fill_zeroes(output, total_bits_with_parity);

    encode(arr, sizeof(arr) / sizeof(arr[0]), TOTAL_BITS, DATA_BITS, output);
    printf("Here are the resulting bits\n");
    for (int i = 1; i <= total_bits_with_parity; i++) 
    {
        if(i % (TOTAL_BITS + 1) == 0)
            continue;
        printf("Output bit %d %b\n", i, output[i]);
    }
    printf("EOL\n");

    return 0;
}


