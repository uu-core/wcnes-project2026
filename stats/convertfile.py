def transform_line(line):
    parts = line.strip().split('|')
    if len(parts) >= 5:
        timestamp = parts[0].strip()
        length = parts[1].strip()
        # parts[2] is removed
        payload = parts[3].strip()
        crc = '|'.join(parts[4:]).strip() 
        return f"{timestamp} | {length} {payload} | {crc}"
    return line

 
input_file = "50K_4.csv"
output_file = input_file.replace('.csv', '_converted.csv')

with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
    for line in infile:
        outfile.write(transform_line(line) + '\n')