/* Run the existing independent API vectors without the optional external
 * soft65c02 harness. sim65 still executes the real compiled 6502 writer. */
#include <stdio.h>
extern unsigned char test_case, test_result;
void test_func(void);
int main(void)
{
    for (test_case = 0; test_case < 23; ++test_case) {
        test_func();
        if (test_result) {
            printf("write vector %u failed: %u\n", test_case, test_result);
            return 1;
        }
    }
    puts("23 independent write API vectors passed");
    return 0;
}
