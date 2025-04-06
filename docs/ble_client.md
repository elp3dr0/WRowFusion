## 🧠 Understanding the Bluetooth Heart Rate Measurement Flags

The **flags** byte is the first byte in a Bluetooth Heart Rate Measurement notification. It uses individual bits to indicate what data is present in the rest of the payload.

### 🔧 Bit Layout of the Flags Byte

Bit position: 7  6  5  4  3  2  1  0
              |  |  |  |  |  |  |  | 
Bit mask:  0x80 40 20 10 08 04 02 01

Each bit is a switch that indicates the presence or format of a specific field.

---

### 📋 Flag Bit Definitions

| Bit | Mask   | Description                                                                 |
|-----|--------|-----------------------------------------------------------------------------|
| 0   | `0x01` | **Heart Rate Format**: `0` = 8-bit, `1` = 16-bit                            |
| 1–2 | `0x06` | **Sensor Contact Status**:  
              `00` = Not supported  
              `10` = Supported, not detected  
              `11` = Supported and detected                                                  |
| 3   | `0x08` | **Energy Expended Present**: If set, 2 bytes of energy expenditure follow   |
| 4   | `0x10` | **RR-Interval Present**: If set, RR-interval(s) follow (2 bytes each)       |
| 5–7 | —      | Reserved for future use                                                    |

---

### 🧪 Example

Suppose `flags = 0b00011011` (or `0x1B`):

- **Bit 0 = 1** → Heart rate is 16-bit  
- **Bits 1–2 = 01** → Sensor contact supported, not detected  
- **Bit 3 = 1** → Energy expenditure data is present  
- **Bit 4 = 1** → RR intervals are present  
- **Bits 5–7 = 0** → Reserved

---

### 🛠️ Usage in Code

```python
flags = data[0]

# Check heart rate format
hr_format_16bit = flags & 0x01

# Check for RR intervals
if flags & 0x10:
    # RR interval data is present

# Check for energy expenditure
if flags & 0x08:
    # Energy expenditure data is present